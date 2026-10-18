"""Sealed, project-held-out TREC 2021 evaluation using external source judgments."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import platform
import re
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path

from evaluation.baselines.bm25 import _evaluate, _write_run
from evaluation.release_source import git
from pipelines.connectors.snapshots import Snapshot, write_json
from pipelines.connectors.trec import KNOWN_2022_LEGACY_HEADER_SHA256, load_qrels, load_topics
from pipelines.embeddings import file_hash, file_record, verify_files

VERSION = "independent-trec2021-v1"
TOPICS_URL = "https://www.trec-cds.org/topics2021.xml"
QRELS_URL = "https://trec.nist.gov/data/trials/qrels2021.txt"
SOURCE_PAGE = "https://www.trec-cds.org/2021.html"
SYSTEMS = ("bm25", "dense", "hybrid", "hybrid-rerank-10", "hybrid-rerank-20")
PACKAGES = ("numpy", "bm25s", "torch", "transformers", "sentence-transformers", "threadpoolctl")


def now() -> str:
    return datetime.now(UTC).isoformat()


def implementation() -> dict:
    return {
        str(p.as_posix()): file_hash(p)
        for package in ("backend", "pipelines", "evaluation")
        for p in sorted(Path(package).rglob("*.py"))
        if "tests" not in p.parts and "__pycache__" not in p.parts
    }


def runtime() -> dict:
    return {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "packages": {name: importlib.metadata.version(name) for name in PACKAGES},
    }


def load_2021_topics(raw: bytes) -> list[dict]:
    """Keep 2021 namespace isolated from the application's 2022-only loader."""
    if (
        len(raw) > 2 * 1024**2
        or b"<!DOCTYPE" in raw.upper()
        or b"<!ENTITY" in raw.upper()
        or hashlib.sha256(raw).hexdigest() == KNOWN_2022_LEGACY_HEADER_SHA256
    ):
        raise ValueError("invalid 2021 topic source")
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise ValueError("invalid topic XML") from exc
    if root.tag != "topics" or root.attrib != {"task": "2021 TREC Clinical Trials"}:
        raise ValueError("unexpected topic task/root")
    rows, seen = [], set()
    for element in root:
        number, text = element.get("number", ""), element.text or ""
        normalized = " ".join(re.findall(r"\w+", text.casefold()))
        if (
            element.tag != "topic"
            or set(element.attrib) != {"number"}
            or len(element)
            or not re.fullmatch(r"[1-9][0-9]*", number)
            or not normalized
            or number in seen
        ):
            raise ValueError("invalid or duplicate topic record")
        seen.add(number)
        rows.append({"topic_id": number, "text": text, "normalized": normalized})
    if not 1 <= len(rows) <= 200:
        raise ValueError("expected 1..200 synthetic topics")
    if len({r["normalized"] for r in rows}) != len(rows):
        raise ValueError("duplicate topic narratives")
    return rows


def overlap_audit(new: list[dict], development: list[dict]) -> dict:
    """Fixed character 5-gram Jaccard gate, before labels; no narrative logging."""

    def grams(text):
        normalized = " ".join(re.findall(r"\w+", text.casefold()))
        return {normalized[i : i + 5] for i in range(max(1, len(normalized) - 4))}

    old = [(r["topic_id"], grams(r["text"])) for r in development]
    nearest = []
    for row in new:
        query = grams(row["text"])
        scores = [(len(query & g) / len(query | g), topic) for topic, g in old]
        score, topic = max(scores)
        nearest.append(
            {"topic_id": row["topic_id"], "development_topic_id": topic, "jaccard": score}
        )
    return {
        "method": "casefold_word_normalization_character_5gram_jaccard",
        "reject_at_or_above": 0.8,
        "nearest_development_cases": nearest,
        "passed": all(r["jaccard"] < 0.8 for r in nearest),
        "limitation": "Lexical screen; semantic or training-data independence is unproven.",
    }


def freeze(study: Path, index: Path, rendered: Path, development: Path, sources: Path) -> dict:
    from backend.app.services.retrieval.reranker import MODEL_DIR, validate_snapshot
    from pipelines.release_index import (
        FROZEN_DOCUMENT_COUNT,
        FROZEN_DOCUMENTS_SHA256,
        source_contract,
        verify_index,
    )

    if study.exists() or sources.exists():
        raise ValueError("fresh study and raw source destinations required")
    manifest = verify_index(index)
    source = source_contract(rendered)
    if (
        manifest["documents"] != FROZEN_DOCUMENT_COUNT
        or source["documents_sha256"] != FROZEN_DOCUMENTS_SHA256
        or manifest["source"] != source
    ):
        raise ValueError("verified full frozen corpus required")
    load_topics(development.read_bytes())
    validate_snapshot(Path("models") / MODEL_DIR)
    protocol = {
        "version": VERSION,
        "frozen_at_utc": now(),
        "base_commit": git(Path.cwd(), "rev-parse", "HEAD").decode().strip(),
        "working_tree_changed": bool(git(Path.cwd(), "status", "--porcelain")),
        "implementation": implementation(),
        "runtime": runtime(),
        "paths": {
            k: str(v)
            for k, v in {
                "index": index,
                "rendered": rendered,
                "development": development,
                "sources": sources,
            }.items()
        },
        "index_manifest_sha256": file_hash(index / "manifest.json"),
        "rendered_manifest_sha256": file_hash(rendered / "manifest.json"),
        "development_topics_sha256": file_hash(development),
        "encoder": manifest["encoder"],
        "reranker_snapshot_sha256": file_hash(Path("models") / MODEL_DIR / "snapshot.json"),
        "documents": FROZEN_DOCUMENT_COUNT,
        "documents_sha256": FROZEN_DOCUMENTS_SHA256,
        "sources": {"topics": TOPICS_URL, "qrels": QRELS_URL, "description": SOURCE_PAGE},
        "systems": list(SYSTEMS),
        "parameters": {
            "representation": "title_conditions",
            "bm25": {"method": "lucene", "k1": 1.2, "b": 0.75},
            "age_sex": "unchanged_legacy_extractor",
            "depth": 100,
            "rrf_k": 60,
            "branch_depth": 100,
            "rerank_depths": [10, 20],
            "reranker_input": "summary_additional_to_title_conditions",
            "tie_break": "NCT_ID",
            "bootstrap": {"seed": 0, "repeats": 10000},
            "overlap_reject_jaccard": 0.8,
        },
        "primary": {"metric": "ndcg_at_10", "candidate": "dense", "baseline": "bm25"},
        "secondary": (
            "hybrid and both rerank depths versus dense; exploratory, no multiplicity adjustment"
        ),
        "independence": {
            "project": "2021 cases not previously used in this project's recorded development",
            "labels": "external TREC judgments; download only after ranking seal",
            "model_training_overlap": "unknown; no contamination-free claim",
            "semantic_case_overlap": "not independently reviewed; fixed lexical audit only",
            "preregistration": "local timestamp and hashes; no external timestamp authority",
        },
        "promotion": False,
    }
    study.mkdir(parents=True)
    write_json(study / "protocol.json", protocol)
    (study / "protocol.sha256").write_text(file_hash(study / "protocol.json"), encoding="ascii")
    return protocol


def check_protocol(study: Path) -> dict:
    if file_hash(study / "protocol.json") != (study / "protocol.sha256").read_text():
        raise ValueError("protocol checksum mismatch")
    protocol = json.loads((study / "protocol.json").read_bytes())
    if (
        protocol["version"] != VERSION
        or protocol["implementation"] != implementation()
        or protocol["runtime"] != runtime()
        or protocol["systems"] != list(SYSTEMS)
    ):
        raise ValueError("frozen code/runtime/configuration changed")
    for name, suffix, key in (
        ("index", "/manifest.json", "index_manifest_sha256"),
        ("rendered", "/manifest.json", "rendered_manifest_sha256"),
        ("development", "", "development_topics_sha256"),
    ):
        if file_hash(Path(protocol["paths"][name] + suffix)) != protocol[key]:
            raise ValueError("frozen input identity changed")
    return protocol


def source_bytes(protocol: dict, kind: str) -> bytes:
    root = Path(protocol["paths"]["sources"]) / kind
    manifest = json.loads((root / "manifest.json").read_bytes())
    filename = "topics2021.xml" if kind == "topics" else "qrels2021.txt"
    if manifest["status"] != "complete" or len(manifest["files"]) != 1:
        raise ValueError("complete single-source snapshot required")
    record = manifest["files"][0]
    if record["url"] != protocol["sources"][kind]:
        raise ValueError("unexpected official source URL")
    verify_files(root, [record], {filename})
    return (root / filename).read_bytes()


def acquire(study: Path, kind: str) -> dict:
    import httpx

    protocol = check_protocol(study)
    if kind == "qrels":
        check_seal(study, protocol)
    elif (study / "seal.json").exists():
        raise ValueError("topics already sealed")
    root = Path(protocol["paths"]["sources"]) / kind
    snapshot = Snapshot(root)
    filename = "topics2021.xml" if kind == "topics" else "qrels2021.txt"
    with httpx.Client(timeout=60, follow_redirects=True) as client:
        raw = snapshot.capture(client, filename, protocol["sources"][kind])
    if kind == "topics":
        rows = load_2021_topics(raw)
        development = load_topics(Path(protocol["paths"]["development"]).read_bytes())
        audit = overlap_audit(rows, development)
        write_json(study / "overlap-audit.json", audit)
        if not audit["passed"]:
            raise ValueError("case overlap gate failed; do not proceed or silently remove cases")
    else:
        topics = load_2021_topics(source_bytes(protocol, "topics"))
        rows = load_qrels(raw, {r["topic_id"] for r in topics})
    manifest = {
        "status": "complete",
        "acquired_at_utc": now(),
        "files": snapshot.files,
        "records": len(rows),
        "protocol_sha256": file_hash(study / "protocol.json"),
    }
    write_json(root / "manifest.json", manifest)
    return {"status": "acquired", "kind": kind, "records": len(rows)}


def rank(study: Path) -> dict:
    import time

    import bm25s
    import numpy as np
    from threadpoolctl import threadpool_limits

    from backend.app.schemas.patient import SyntheticCase
    from backend.app.services.retrieval.hybrid import reciprocal_rank_fusion
    from backend.app.services.retrieval.reranker import MODEL_DIR, LocalReranker, reorder
    from backend.app.services.retrieval.sparse import tokenize
    from evaluation.baselines.filters import (
        extract_topic_demographics,
        not_deterministically_incompatible,
    )
    from evaluation.release_benchmark import top_indices
    from pipelines.embeddings import MODELS, LocalSentenceEncoder
    from pipelines.release_index import read_chunk, source_contract, verify_index

    protocol = check_protocol(study)
    if (Path(protocol["paths"]["sources"]) / "qrels").exists():
        raise ValueError("judgments acquired before ranking; use the existing sealed rankings")
    output = study / "ranked"
    if output.exists() or (study / "seal.json").exists():
        raise ValueError("rank output is immutable; a failed attempt remains inspectable")
    topics_raw = source_bytes(protocol, "topics")
    topics = load_2021_topics(topics_raw)
    audit = overlap_audit(topics, load_topics(Path(protocol["paths"]["development"]).read_bytes()))
    if not audit["passed"]:
        raise ValueError("case overlap gate failed")
    index, rendered = Path(protocol["paths"]["index"]), Path(protocol["paths"]["rendered"])
    manifest = verify_index(index)
    if source_contract(rendered) != manifest["source"]:
        raise ValueError("full render/index contract mismatch")
    if (
        file_hash(Path("models") / MODEL_DIR / "snapshot.json")
        != protocol["reranker_snapshot_sha256"]
    ):
        raise ValueError("frozen reranker changed")
    encoder = LocalSentenceEncoder(MODELS["minilm"], Path("models"))
    if encoder.metadata != protocol["encoder"]:
        raise ValueError("query/document encoder mismatch")
    output.mkdir()
    rows, arrays = [], []
    for chunk in manifest["chunks"]:
        part, vectors = read_chunk(index / chunk["directory"], chunk)
        rows.extend(part)
        arrays.append(vectors)
    matrix = np.concatenate(arrays)
    del arrays
    ids = np.array([r["trial_id"] for r in rows])
    write_json(output / "corpus-ids.json", ids.tolist())
    lexical = bm25s.BM25(k1=1.2, b=0.75, method="lucene")
    lexical.index(
        bm25s.tokenize(
            [r["text"] for r in rows],
            lower=True,
            stopwords="english",
            return_ids=True,
            show_progress=False,
        ),
        show_progress=False,
    )
    rankings = {name: {} for name in SYSTEMS}
    timings, cases, query_audit = [], [], []
    for topic in topics:
        case = SyntheticCase(
            case_id=f"trec-ct-2021:{topic['topic_id']}",
            synthetic=True,
            text=topic["text"],
            source=SOURCE_PAGE,
            source_sha256=hashlib.sha256(topics_raw).hexdigest(),
            source_locator=f"/topics/topic[@number='{topic['topic_id']}']",
        )
        cases.append(case)
        encoded = encoder.encode([case.text])
        query_audit.append(
            {
                "topic_id": topic["topic_id"],
                "tokens": encoded.token_counts[0],
                "truncated": encoded.token_counts[0] > encoder.spec.max_tokens,
            }
        )
        started = time.perf_counter()
        with threadpool_limits(limits=4, user_api="blas"):
            dense = matrix @ encoded.vectors[0]
            reference = np.concatenate(
                [matrix[i : i + 4096] @ encoded.vectors[0] for i in range(0, len(rows), 4096)]
            )
        if not np.allclose(dense, reference, atol=1e-6, rtol=0):
            raise ValueError("independent exact reference mismatch")
        sparse = lexical.get_scores(tokenize([case.text])[0])
        facts = extract_topic_demographics(case.text)
        allowed = np.array(
            [not_deterministically_incompatible(facts, r["filter_metadata"]) for r in rows]
        )
        branches = {}
        for method, scores in (("dense", dense), ("bm25", sparse)):
            selected = top_indices(scores, ids, allowed, positive=method == "bm25")
            hits = [{"trial_id": str(ids[i]), "score": float(scores[i])} for i in selected]
            rankings[method][topic["topic_id"]] = hits
            branches["sparse" if method == "bm25" else "dense"] = [
                {"payload": {"trial_id": h["trial_id"]}, "score": h["score"]} for h in hits
            ]
        rankings["hybrid"][topic["topic_id"]] = reciprocal_rank_fusion(branches, k=100)
        timings.append(
            {
                "topic_id": topic["topic_id"],
                "retrieval_and_reference_seconds": time.perf_counter() - started,
            }
        )
        print(
            json.dumps({"stage": "ranked_without_labels", "topic": topic["topic_id"]}), flush=True
        )
    needed = {h["trial_id"] for hits in rankings["hybrid"].values() for h in hits[:20]}
    summaries = {}
    with (rendered / "documents.jsonl").open("rb") as handle:
        for raw in handle:
            row = json.loads(raw)
            if row["trial_id"] in needed:
                summaries[row["trial_id"]] = row["representations"]["summary"]
    if set(summaries) != needed:
        raise ValueError("reranker source coverage mismatch")
    reranker = LocalReranker()
    for case, topic in zip(cases, topics, strict=True):
        base = rankings["hybrid"][topic["topic_id"]]
        if len(base) < 20:
            raise ValueError("frozen rerank depths require at least 20 candidates")
        for depth in (10, 20):
            scores = reranker.score(case, [summaries[h["trial_id"]] for h in base[:depth]])
            rankings[f"hybrid-rerank-{depth}"][topic["topic_id"]] = reorder(base, scores)
    validate_rankings(rankings, {r["topic_id"] for r in topics}, set(ids))
    write_json(output / "rankings.json", rankings)
    write_json(output / "query-audit.json", query_audit)
    write_json(output / "timings.json", timings)
    write_json(output / "models.json", {"encoder": encoder.metadata, "reranker": reranker.metadata})
    for name, results in rankings.items():
        # Monotonic rank surrogates preserve ties/prefix order; original scores stay in JSON.
        pairs = {
            t: [(h["trial_id"], float(len(hits) - i)) for i, h in enumerate(hits)]
            for t, hits in results.items()
        }
        _write_run(output / f"{name}.run", pairs, name)
    check_protocol(study)
    seal = {
        "sealed_at_utc": now(),
        "protocol_sha256": file_hash(study / "protocol.json"),
        "topics_sha256": hashlib.sha256(topics_raw).hexdigest(),
        "files": [file_record(p, output) for p in sorted(output.iterdir())],
        "topics": len(topics),
        "systems": list(SYSTEMS),
    }
    write_json(study / "seal.json", seal)
    return {"status": "rankings_sealed", "topics": len(topics), "systems": len(SYSTEMS)}


def validate_rankings(rankings: dict, topics: set[str], corpus: set[str]) -> None:
    import math

    if set(rankings) != set(SYSTEMS):
        raise ValueError("all frozen systems required")
    for results in rankings.values():
        if set(results) != topics:
            raise ValueError("all topics required; no missing-topic averaging")
        for hits in results.values():
            ids = [h["trial_id"] for h in hits]
            if (
                len(hits) > 100
                or len(ids) != len(set(ids))
                or set(ids) - corpus
                or any(not math.isfinite(h["score"]) for h in hits)
            ):
                raise ValueError("invalid ranking IDs, depth or scores")


def check_seal(study: Path, protocol: dict) -> dict:
    seal = json.loads((study / "seal.json").read_bytes())
    if (
        seal["protocol_sha256"] != file_hash(study / "protocol.json")
        or seal["topics_sha256"] != hashlib.sha256(source_bytes(protocol, "topics")).hexdigest()
        or seal["systems"] != list(SYSTEMS)
    ):
        raise ValueError("ranking seal identity mismatch")
    expected = {
        "rankings.json",
        "corpus-ids.json",
        "query-audit.json",
        "timings.json",
        "models.json",
    }
    expected.update(f"{name}.run" for name in SYSTEMS)
    verify_files(study / "ranked", seal["files"], expected)
    return seal


def score_rankings(
    rankings: dict, judgments: list[dict], topics: set[str], corpus: set[str]
) -> dict:
    from evaluation.release_benchmark import paired_interval
    from evaluation.reranking import comparison

    validate_rankings(rankings, topics, corpus)
    if {r["topic_id"] for r in judgments} != topics or {r["trial_id"] for r in judgments} - corpus:
        raise ValueError("every topic needs judgments, all judged trials must be in the corpus")
    metrics, per_topic, coverage = {}, {}, {}
    judged = {(r["topic_id"], r["trial_id"]) for r in judgments}
    for name, results in rankings.items():
        pairs = {t: [(h["trial_id"], h["score"]) for h in hits] for t, hits in results.items()}
        metrics[name], per_topic[name] = _evaluate(pairs, judgments)
        coverage[name] = {
            t: sum((t, h["trial_id"]) in judged for h in hits[:10]) / 10
            for t, hits in results.items()
        }
    contrasts = {}
    for candidate, baseline in (
        ("dense", "bm25"),
        ("hybrid", "dense"),
        ("hybrid-rerank-10", "dense"),
        ("hybrid-rerank-20", "dense"),
    ):
        interval = paired_interval(per_topic[baseline], per_topic[candidate])
        interval.pop("held_out")
        if candidate == "dense":
            interval["multiple_comparison_adjustment"] = "one prespecified primary comparison"
        contrasts[f"{candidate}_vs_{baseline}"] = {
            **comparison(per_topic[baseline], per_topic[candidate]),
            **interval,
            "role": "primary" if candidate == "dense" else "exploratory_secondary",
        }
    return {
        "metrics": metrics,
        "per_topic": per_topic,
        "comparisons": contrasts,
        "judged_fraction_at_10": coverage,
    }


def score(study: Path) -> dict:
    if (study / "evaluation.json").exists():
        raise ValueError("completed evaluation is immutable")
    protocol = check_protocol(study)
    seal = check_seal(study, protocol)
    topics = load_2021_topics(source_bytes(protocol, "topics"))
    ids = {r["topic_id"] for r in topics}
    judgments = load_qrels(source_bytes(protocol, "qrels"), ids)
    ranked = study / "ranked"
    corpus = json.loads((ranked / "corpus-ids.json").read_bytes())
    if len(corpus) != protocol["documents"] or len(set(corpus)) != len(corpus):
        raise ValueError("full corpus identity count mismatch")
    report = score_rankings(
        json.loads((ranked / "rankings.json").read_bytes()), judgments, ids, set(corpus)
    )
    report.update(
        {
            "version": VERSION,
            "status": "complete",
            "scored_at_utc": now(),
            "protocol_sha256": file_hash(study / "protocol.json"),
            "seal_sha256": file_hash(study / "seal.json"),
            "rankings_sealed_at_utc": seal["sealed_at_utc"],
            "qrels_sha256": hashlib.sha256(source_bytes(protocol, "qrels")).hexdigest(),
            "topics": len(topics),
            "judgments": len(judgments),
            "documents": len(corpus),
            "independence": protocol["independence"],
            "promotion": False,
            "limitations": [
                "External pooled judgments; unjudged zero gain is not established irrelevance.",
                "MRR truncated at 100; source grade 2/1 recall is not clinical accuracy.",
                "Reranker adds summary text; not a controlled model-only comparison.",
                "Project configuration holdout; no certified model-training independence.",
                "Local sequencing seal; no external registration or adversarial access control.",
                "No independent criterion labels or clinical validation.",
            ],
        }
    )
    write_json(study / "evaluation.json", report)
    (study / "evaluation.sha256").write_text(file_hash(study / "evaluation.json"), encoding="ascii")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action", choices=["freeze", "acquire-topics", "rank", "acquire-qrels", "score", "verify"]
    )
    parser.add_argument("--study", type=Path, required=True)
    parser.add_argument("--index", type=Path, default=Path("data/processed/release-full-minilm-v2"))
    parser.add_argument(
        "--rendered", type=Path, default=Path("data/processed/trec-ct-2021-render-v1")
    )
    parser.add_argument(
        "--development", type=Path, default=Path("data/raw/m1-20260831-500-v2/topics2022.xml")
    )
    parser.add_argument("--sources", type=Path, default=Path("data/raw/independent-trec2021-v1"))
    args = parser.parse_args()
    if args.action == "freeze":
        freeze(args.study, args.index, args.rendered, args.development, args.sources)
        result = {"status": "frozen", "version": VERSION}
    elif args.action.startswith("acquire-"):
        result = acquire(args.study, args.action.split("-")[1])
    elif args.action == "rank":
        result = rank(args.study)
    elif args.action == "score":
        report = score(args.study)
        result = {k: report[k] for k in ("status", "topics", "judgments", "metrics")}
    else:
        protocol = check_protocol(args.study)
        seal = check_seal(args.study, protocol)
        if (args.study / "evaluation.json").exists():
            if (
                file_hash(args.study / "evaluation.json")
                != (args.study / "evaluation.sha256").read_text()
            ):
                raise ValueError("evaluation checksum mismatch")
            report = json.loads((args.study / "evaluation.json").read_bytes())
            if (
                report["seal_sha256"] != file_hash(args.study / "seal.json")
                or report["qrels_sha256"]
                != hashlib.sha256(source_bytes(protocol, "qrels")).hexdigest()
            ):
                raise ValueError("evaluation source identity mismatch")
        result = {"status": "verified", "topics": seal["topics"], "systems": seal["systems"]}
    print(json.dumps(result), flush=True)


if __name__ == "__main__":
    main()
