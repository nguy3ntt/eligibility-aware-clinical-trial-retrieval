"""Separate immutable MiniLM field/passage artifact and explicit preparation/search CLI."""

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

from pipelines.connectors.snapshots import write_json
from pipelines.criteria.artifacts import local_id
from pipelines.embeddings import file_hash, file_record, validate_vectors, verify_files
from pipelines.indexing.qdrant import artifact_contract
from pipelines.reranking_data import load_evidence, validate_record

VERSION = "field-passages-v1"
FIELDS = ("brief_summary", "detailed_description", "interventions")
PARAMETERS = {
    "passage_tokens": 192,
    "overlap_tokens": 32,
    "field_pooling": "max_cosine_per_trial_per_field",
    "fusion": "equal_branch_rrf",
    "rrf_constant": 60,
    "branch_depth": 100,
    "query": "unchanged_full_narrative_right_truncated",
    "eligibility_text_indexed": False,
    "max_trials": 512,
    "max_segments": 50000,
}


def windows(text, tokenizer):
    offsets = tokenizer(
        text, add_special_tokens=False, return_offsets_mapping=True, truncation=False, verbose=False
    )["offset_mapping"]
    if not offsets:
        if text.strip():
            raise ValueError("nonempty text has no token offsets")
        return []
    if any(not 0 <= a < b <= len(text) for a, b in offsets):
        raise ValueError("invalid tokenizer character offsets")
    result = []
    size, overlap = PARAMETERS["passage_tokens"], PARAMETERS["overlap_tokens"]
    start = 0
    while start < len(offsets):
        end = min(start + size, len(offsets))
        a, b = offsets[start][0], offsets[end - 1][1]
        result.append(
            {"start": a, "end": b, "text": text[a:b], "token_start": start, "token_end": end}
        )
        if end == len(offsets):
            break
        start = end - overlap
    return result


def segments_for(records, tokenizer):
    """Offsets refer to each ORIGINAL XML text item, never a reconstructed paraphrase."""
    segments = {"summary": [], "fields": [], "passages": []}
    for record in records:
        validate_record(record)
        trial_id = record["trial_id"]
        segments["summary"].append(
            {
                "trial_id": trial_id,
                "field": "summary",
                "text": record["row"]["representations"]["summary"],
                "source_sha256": record["source_sha256"],
                "locator": "rendered:summary",
                "original_item": None,
                "start": None,
                "end": None,
            }
        )
        for name in FIELDS:
            field = record["fields"][name]
            for item, text in enumerate(field["original_texts"]):
                if not text.strip():
                    continue
                base = {
                    "trial_id": trial_id,
                    "field": name,
                    "source_sha256": record["source_sha256"],
                    "locator": field["locator"],
                    "original_item": item,
                }
                segments["fields"].append({**base, "start": 0, "end": len(text), "text": text})
                segments["passages"].extend({**base, **part} for part in windows(text, tokenizer))
        if sum(map(len, segments.values())) > PARAMETERS["max_segments"]:
            raise ValueError("bounded field/passage inventory exceeded")
    return segments


def build(index, evidence, output, encoder, *, batch_size=32):
    if not 1 <= batch_size <= 64:
        raise ValueError("batch size must be 1..64")
    contract, rows, baseline = artifact_contract(index)
    if not 1 <= len(rows) <= PARAMETERS["max_trials"]:
        raise ValueError("bounded source artifact required")
    records = list(load_evidence(evidence, rows, contract["artifact_sha256"]).values())
    if encoder.metadata["snapshot_sha256"] != contract["snapshot_sha256"]:
        raise ValueError("query/document model identity differs")
    # Use the exact tokenizer of the pinned encoder, with no download fallback.
    segments = segments_for(records, encoder.model.tokenizer)
    output.mkdir(parents=True, exist_ok=False)
    started = time.perf_counter()
    try:
        np.save(output / "baseline.npy", baseline, allow_pickle=False)
        statistics = {}
        for variant, parts in segments.items():
            if not parts:
                raise ValueError("each comparison requires nonempty fields")
            vectors, counts = [], []
            for start in range(0, len(parts), batch_size):
                batch = encoder.encode([p["text"] for p in parts[start : start + batch_size]])
                validate_vectors(batch.vectors, len(batch.token_counts), encoder.spec.dimension)
                vectors.append(batch.vectors)
                counts.extend(batch.token_counts)
            if len(counts) != len(parts):
                raise ValueError("encoder row counts differ")
            for part, count in zip(parts, counts, strict=True):
                part["token_count"] = count
                part["truncated"] = count > encoder.spec.max_tokens
            if variant == "passages" and any(p["truncated"] for p in parts):
                raise ValueError("passage unexpectedly exceeds model token budget")
            np.save(output / f"{variant}.npy", np.concatenate(vectors), allow_pickle=False)
            statistics[variant] = {
                "segments": len(parts),
                "truncated": sum(p["truncated"] for p in parts),
            }
            print(f"Prepared {variant}: {len(parts)} segments", file=sys.stderr)
        write_json(output / "segments.json", segments)
        manifest = {
            "version": VERSION,
            "status": "complete",
            "parameters": PARAMETERS,
            "source_contract": contract,
            "evidence_manifest_sha256": file_hash(evidence / "manifest.json"),
            "encoder": encoder.metadata,
            "trial_ids": [r["trial_id"] for r in rows],
            "statistics": statistics,
            "build_seconds": time.perf_counter() - started,
            "implementation_sha256": file_hash(Path(__file__)),
            "files": [file_record(p, output) for p in sorted(output.iterdir())],
            "benchmark_comparable": False,
            "default_retrieval_changed": False,
        }
        write_json(output / "manifest.json", manifest)
        return manifest
    except Exception as exc:
        write_json(output / "failure.json", {"status": "failed", "error_type": type(exc).__name__})
        raise


def load(root, index, evidence):
    manifest = json.loads((root / "manifest.json").read_bytes())
    required = {"baseline.npy", "summary.npy", "fields.npy", "passages.npy", "segments.json"}
    if (
        manifest.get("version") != VERSION
        or manifest.get("status") != "complete"
        or manifest.get("parameters") != PARAMETERS
        or manifest.get("implementation_sha256") != file_hash(Path(__file__))
    ):
        raise ValueError("passage implementation/configuration changed; rebuild under a new ID")
    verify_files(root, manifest["files"], required)
    contract, rows, baseline = artifact_contract(index)
    records = load_evidence(evidence, rows, contract["artifact_sha256"])
    if (
        manifest["source_contract"] != contract
        or manifest["evidence_manifest_sha256"] != file_hash(evidence / "manifest.json")
        or manifest["encoder"]["snapshot_sha256"] != contract["snapshot_sha256"]
        or manifest["trial_ids"] != [r["trial_id"] for r in rows]
    ):
        raise ValueError("field/passage artifact is not aligned with source catalog")
    parts = json.loads((root / "segments.json").read_bytes())
    vectors = {}
    if set(parts) != {"summary", "fields", "passages"}:
        raise ValueError("variant inventory mismatch")
    if sum(map(len, parts.values())) > PARAMETERS["max_segments"]:
        raise ValueError("passage bound exceeded")
    expected_fields = {
        (tid, name, i)
        for tid, record in records.items()
        for name in FIELDS
        for i, original in enumerate(record["fields"][name]["original_texts"])
        if original.strip()
    }
    for variant, segments in parts.items():
        vectors[variant] = np.load(root / f"{variant}.npy", allow_pickle=False)
        validate_vectors(vectors[variant], len(segments), contract["dimension"])
        seen = set()
        for part in segments:
            record = records[part["trial_id"]]
            key = (
                part["trial_id"],
                part["field"],
                part["original_item"],
                part["start"],
                part["end"],
            )
            if key in seen or part["source_sha256"] != record["source_sha256"]:
                raise ValueError("duplicate or mismatched passage source")
            seen.add(key)
            if variant == "summary":
                expected = record["row"]["representations"]["summary"]
                if part["field"] != "summary" or part["locator"] != "rendered:summary":
                    raise ValueError("invalid summary field")
            else:
                if part["field"] not in FIELDS:
                    raise ValueError("unapproved retrieval field")
                field = record["fields"][part["field"]]
                original = field["original_texts"][part["original_item"]]
                if (
                    not isinstance(part["original_item"], int)
                    or part["original_item"] < 0
                    or not 0 <= part["start"] < part["end"] <= len(original)
                    or part["locator"] != field["locator"]
                ):
                    raise ValueError("invalid original field span")
                expected = original[part["start"] : part["end"]]
                if variant == "fields" and (part["start"] != 0 or part["end"] != len(original)):
                    raise ValueError("whole-field comparison lost content")
            if (
                part["text"] != expected
                or not isinstance(part["token_count"], int)
                or part["token_count"] < 1
            ):
                raise ValueError("passage text or token metadata differs")
            if part["truncated"] != (part["token_count"] > contract["model"]["max_tokens"]):
                raise ValueError("truncation metadata differs")
            if variant == "passages" and part["truncated"]:
                raise ValueError("truncated passage")
        actual_stats = {
            "segments": len(segments),
            "truncated": sum(p["truncated"] for p in segments),
        }
        if manifest["statistics"][variant] != actual_stats:
            raise ValueError("segment statistics differ")
        identities = [(p["trial_id"], p["field"], p["original_item"]) for p in segments]
        if variant == "summary":
            if len(segments) != len(rows) or {p["trial_id"] for p in segments} != set(records):
                raise ValueError("missing summary rows")
        elif set(identities) != expected_fields:
            raise ValueError("missing original field inventory")
        if variant == "passages":
            for tid, name, item in sorted(expected_fields):
                chunks = [
                    p
                    for p in segments
                    if (p["trial_id"], p["field"], p["original_item"]) == (tid, name, item)
                ]
                original = records[tid]["fields"][name]["original_texts"][item]
                if (
                    chunks[0]["token_start"] != 0
                    or original[: chunks[0]["start"]].strip()
                    or original[chunks[-1]["end"] :].strip()
                ):
                    raise ValueError("incomplete passage coverage")
                for i, chunk in enumerate(chunks):
                    if (
                        not 0
                        < chunk["token_end"] - chunk["token_start"]
                        <= PARAMETERS["passage_tokens"]
                    ):
                        raise ValueError("invalid token window")
                    if i and (
                        chunk["token_start"]
                        != chunks[i - 1]["token_end"] - PARAMETERS["overlap_tokens"]
                        or chunk["end"] <= chunks[i - 1]["end"]
                        or chunk["start"] > chunks[i - 1]["end"]
                    ):
                        raise ValueError("passage window gap/order differs")
    saved = np.load(root / "baseline.npy", allow_pickle=False)
    if not np.array_equal(saved, baseline):
        raise ValueError("baseline vectors changed")
    vectors["baseline"] = saved
    return manifest, rows, records, parts, vectors


def rank(loaded, query, *, variant="passages", demographics=None, k=100):
    from evaluation.baselines.filters import not_deterministically_incompatible

    if variant not in {"baseline", "summary", "fields", "passages"} or not 1 <= k <= 100:
        raise ValueError("unsupported retrieval variant/depth")
    manifest, rows, records, parts, vectors = loaded
    validate_vectors(np.asarray(query).reshape(1, -1), 1, manifest["source_contract"]["dimension"])
    allowed = {
        r["trial_id"]
        for r in rows
        if demographics is None
        or not_deterministically_incompatible(demographics, r["filter_metadata"])
    }
    branches = {}

    def branch(name, segments, matrix):
        best = {}
        scores = np.clip(matrix @ query, -1, 1)
        for i, (segment, score) in enumerate(zip(segments, scores, strict=True)):
            tid = segment["trial_id"]
            if tid not in allowed:
                continue
            if tid not in best or float(score) > best[tid][0]:
                best[tid] = (float(score), i)
        branches[name] = [
            {
                "trial_id": tid,
                "rank": ordinal,
                "raw_score": value[0],
                "score_kind": "cosine_similarity",
                "segment": segments[value[1]],
            }
            for ordinal, (tid, value) in enumerate(
                sorted(best.items(), key=lambda x: (-x[1][0], x[0]))[:100], 1
            )
        ]

    baseline_parts = [
        {
            "trial_id": r["trial_id"],
            "field": "title_conditions",
            "text": r["representations"]["title_conditions"],
            "source_sha256": records[r["trial_id"]]["source_sha256"],
            "locator": "rendered:title_conditions",
            "original_item": None,
            "start": None,
            "end": None,
        }
        for r in rows
    ]
    if variant in {"baseline", "fields", "passages"}:
        branch("title_conditions", baseline_parts, vectors["baseline"])
    if variant == "summary":
        branch("summary", parts[variant], vectors[variant])
    if variant in {"fields", "passages"}:
        for name in FIELDS:
            selected = [i for i, p in enumerate(parts[variant]) if p["field"] == name]
            if selected:
                branch(name, [parts[variant][i] for i in selected], vectors[variant][selected])
    combined = {}
    for name, candidates in branches.items():
        for item in candidates:
            tid = item["trial_id"]
            entry = combined.setdefault(tid, {"trial_id": tid, "score": 0.0, "branches": {}})
            contribution = 1 / (PARAMETERS["rrf_constant"] + item["rank"])
            entry["score"] += (
                contribution if variant in {"fields", "passages"} else item["raw_score"]
            )
            entry["branches"][name] = {
                **item,
                "rrf_contribution": contribution if variant in {"fields", "passages"} else None,
            }
    ranking = sorted(combined.values(), key=lambda r: (-r["score"], r["trial_id"]))[:k]
    row_map = {r["trial_id"]: r for r in rows}
    for i, item in enumerate(ranking, 1):
        row = row_map[item["trial_id"]]
        item.update(
            rank=i,
            original_rank=i,
            reranker=None,
            score_kind="reciprocal_rank_fusion"
            if variant in {"fields", "passages"}
            else "cosine_similarity",
            payload={
                "trial_id": row["trial_id"],
                "source": row["source"],
                "content_sha256": row["content_sha256"],
                "filter_metadata": row["filter_metadata"],
            },
        )
    return ranking


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["build", "verify", "search"])
    parser.add_argument("--index-id", type=local_id, default="dense-m3-minilm-v1")
    parser.add_argument("--evidence-id", type=local_id, default="reranking-evidence-v1")
    parser.add_argument("--output-id", type=local_id, default="field-passages-v2")
    parser.add_argument(
        "--topics", type=Path, default=Path("data/raw/m1-20260831-500-v2/topics2022.xml")
    )
    parser.add_argument("--case-id", default="trec-ct-2022:29")
    args = parser.parse_args()
    index, evidence, output = [
        Path("data/processed") / value
        for value in (args.index_id, args.evidence_id, args.output_id)
    ]
    try:
        if args.command == "build":
            from pipelines.embeddings import MODELS, LocalSentenceEncoder

            result = build(
                index, evidence, output, LocalSentenceEncoder(MODELS["minilm"], Path("models"))
            )
            print(json.dumps({k: result[k] for k in ("status", "statistics", "build_seconds")}))
        else:
            loaded = load(output, index, evidence)
            if args.command == "verify":
                print(
                    json.dumps(
                        {
                            "status": "verified",
                            "trials": len(loaded[1]),
                            "statistics": loaded[0]["statistics"],
                        }
                    )
                )
            else:
                from evaluation.baselines.filters import extract_topic_demographics
                from pipelines.connectors.synthetic_cases import load_cases
                from pipelines.embeddings import MODELS, LocalSentenceEncoder

                case = next(
                    c for c in load_cases(args.topics, topics=True) if c.case_id == args.case_id
                )
                encoder = LocalSentenceEncoder(MODELS["minilm"], Path("models"))
                if encoder.metadata != loaded[0]["encoder"]:
                    raise ValueError("query encoder/runtime differs from passage artifact")
                batch = encoder.encode([case.text])
                print(
                    json.dumps(
                        {
                            "case_id": case.case_id,
                            "query_truncated": batch.token_counts[0] > encoder.spec.max_tokens,
                            "results": rank(
                                loaded,
                                batch.vectors[0],
                                demographics=extract_topic_demographics(case.text),
                                k=3,
                            ),
                        },
                        indent=2,
                    )
                )
    except (ValueError, OSError, KeyError, TypeError, StopIteration, ImportError) as exc:
        parser.exit(
            1, f"Field/passage operation failed ({type(exc).__name__}); check artifact contracts.\n"
        )


if __name__ == "__main__":
    main()
