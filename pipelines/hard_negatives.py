"""Deterministic, double-group-disjoint relevance pairs from inspected synthetic topics."""

import argparse
import json
import re
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from backend.app.schemas.patient import SyntheticCase, text_hash
from backend.app.services.retrieval.sparse import SparseBM25
from evaluation.baselines.filters import (
    extract_topic_demographics,
    not_deterministically_incompatible,
)
from pipelines.connectors.snapshots import write_json
from pipelines.connectors.synthetic_cases import load_cases
from pipelines.connectors.trec import load_qrels
from pipelines.criteria.artifacts import local_id
from pipelines.embeddings import file_hash, file_record, verify_files
from pipelines.indexing.qdrant import artifact_contract
from pipelines.reranking_data import load_evidence

VERSION = "domain-hard-negative-data-v1"
PARTITIONS = ("train", "dev", "test")
PARAMETERS = {
    "seed": "domain-hard-negatives-v1",
    "split_percentages": [60, 20, 20],
    "case_word5_jaccard": 0.8,
    "trial_word5_jaccard": 0.85,
    "minimum_near_duplicate_shingles": 10,
    "branch_depth": 50,
    "dense_confusable_depth": 20,
    "positive_limit_per_case": 4,
    "negative_limit_per_case": 2,
    "positive_grades": [1, 2],
    "negative_grade": 0,
    "fusion_constant": 60,
    "candidate_depth": 100,
    "rerank_depth": 20,
    "split_unit": "case_group_AND_trial_group",
    "held_out_from_project_development": False,
}
DEFAULT_DATA = "domain-hard-negatives-v1"
INDEX = Path("data/processed/dense-m3-minilm-v1")
EVIDENCE = Path("data/processed/reranking-evidence-v1")
TOPICS = Path("data/raw/m1-20260831-500-v2/topics2022.xml")
QRELS = TOPICS.with_name("qrels2022.txt")


def normalize(text):
    return " ".join(re.findall(r"\w+", text.casefold()))


def shingles(text):
    words = normalize(text).split()
    return {tuple(words[i : i + 5]) for i in range(max(0, len(words) - 4))}


def group_records(texts, *, threshold, exact_keys=None):
    """Lexical connected components, not proof of semantic or protocol-family independence."""
    ids = sorted(texts)
    parent = {identity: identity for identity in ids}

    def find(identity):
        while identity != parent[identity]:
            parent[identity] = parent[parent[identity]]
            identity = parent[identity]
        return identity

    grams = {identity: shingles(texts[identity]) for identity in ids}
    comparisons = 0
    for i, left in enumerate(ids):
        for right in ids[i + 1 :]:
            a, b = grams[left], grams[right]
            exact = normalize(texts[left]) == normalize(texts[right])
            if exact_keys:
                exact |= bool(exact_keys[left]) and exact_keys[left] == exact_keys[right]
            similar = False
            if min(len(a), len(b)) >= PARAMETERS["minimum_near_duplicate_shingles"]:
                comparisons += 1
                similar = len(a & b) / len(a | b) >= threshold
            if exact or similar:
                x, y = sorted((find(left), find(right)))
                parent[y] = x
    groups = {}
    for identity in ids:
        groups.setdefault(find(identity), []).append(identity)
    assignment = {
        member: text_hash("\n".join(members)) for members in groups.values() for member in members
    }
    return assignment, {
        "groups": len(groups),
        "multi_record_groups": sum(len(g) > 1 for g in groups.values()),
        "largest_group": max(map(len, groups.values()), default=0),
        "near_comparisons": comparisons,
    }


def partition(group, kind):
    bucket = int(text_hash(PARAMETERS["seed"] + ":" + kind + ":" + group)[:8], 16) % 100
    return "train" if bucket < 60 else "dev" if bucket < 80 else "test"


def make_split(cases, records):
    case_groups, case_audit = group_records(
        {c.case_id: c.text for c in cases}, threshold=PARAMETERS["case_word5_jaccard"]
    )
    texts = {tid: r["row"]["representations"]["summary"] for tid, r in records.items()}
    keys = {
        tid: normalize(
            r["fields"]["official_title"]["normalized"] or r["fields"]["brief_title"]["normalized"]
        )
        + "|"
        + normalize(r["fields"]["conditions"]["normalized"])
        for tid, r in records.items()
    }
    trial_groups, trial_audit = group_records(
        texts, threshold=PARAMETERS["trial_word5_jaccard"], exact_keys=keys
    )
    split = {
        "case_groups": case_groups,
        "trial_groups": trial_groups,
        "cases": {i: partition(g, "case") for i, g in case_groups.items()},
        "trials": {i: partition(g, "trial") for i, g in trial_groups.items()},
        "audit": {
            "case": case_audit,
            "trial": trial_audit,
            "semantic_family_disjointness_proven": False,
        },
    }
    validate_split(split, {c.case_id for c in cases}, set(records))
    return split


def validate_split(split, cases, trials):
    for kind, groups, expected in (
        ("cases", "case_groups", cases),
        ("trials", "trial_groups", trials),
    ):
        if set(split[kind]) != expected or set(split[groups]) != expected:
            raise ValueError("split must retain all source identities")
        seen = {}
        for identity, assigned in split[kind].items():
            group = split[groups][identity]
            if assigned not in PARTITIONS or assigned != partition(
                group, "case" if kind == "cases" else "trial"
            ):
                raise ValueError("split differs from fixed group hash")
            if group in seen and seen[group] != assigned:
                raise ValueError("group leakage")
            seen[group] = assigned
    return split


def mine_pairs(case, labels, dense, lexical, conditions):
    """Only externally judged grade zero can become a negative; grade one stays relevant."""
    ranks = [{tid: i + 1 for i, (tid, _) in enumerate(branch)} for branch in (dense, lexical)]
    scores = [dict(branch) for branch in (dense, lexical)]
    positives = []
    for grade in (1, 2):
        selected = sorted(
            (tid for tid, value in labels.items() if value == grade),
            key=lambda tid: text_hash(case.case_id + ":positive:" + tid),
        )
        positives.extend(selected[:2])
    positives = sorted(positives)[: PARAMETERS["positive_limit_per_case"]]
    query_terms = set(re.findall(r"[a-z][a-z0-9]+", case.text.casefold()))
    negatives, audits = [], {}
    for tid, grade in labels.items():
        if grade != 0:
            continue
        rank = [r.get(tid) for r in ranks]
        in_pool = any(r is not None and r <= PARAMETERS["branch_depth"] for r in rank)
        overlap = sorted(
            query_terms & set(re.findall(r"[a-z][a-z0-9]+", conditions[tid].casefold()))
        )
        confusable = rank[0] is not None and rank[0] <= PARAMETERS["dense_confusable_depth"]
        if not in_pool or not (overlap or confusable):
            continue
        fusion = sum(
            1 / (PARAMETERS["fusion_constant"] + r)
            for r in rank
            if r is not None and r <= PARAMETERS["branch_depth"]
        )
        audits[tid] = {
            "negative_grade": 0,
            "dense_rank": rank[0],
            "bm25_rank": rank[1],
            "dense_score": scores[0].get(tid),
            "bm25_score": scores[1].get(tid),
            "mining_rrf": fusion,
            "source_condition_overlap_terms": overlap,
            "reason": "source_condition_overlap" if overlap else "high_dense_rank",
        }
        negatives.append(tid)
    negatives.sort(key=lambda tid: (-audits[tid]["mining_rrf"], tid))
    hard = negatives[: PARAMETERS["negative_limit_per_case"]]
    random = sorted(
        (tid for tid, value in labels.items() if value == 0),
        key=lambda tid: text_hash(PARAMETERS["seed"] + case.case_id + ":random:" + tid),
    )[: len(hard)]
    if not positives or not hard:
        return (
            [],
            [],
            {
                "case_id": case.case_id,
                "reason": "no_positive" if not positives else "no_judged_confusable_negative",
            },
        )
    variants = []
    for name, chosen in (("hard", hard), ("random", random)):
        variants.append(
            [
                {
                    "case_id": case.case_id,
                    "positive_id": pos,
                    "negative_id": neg,
                    "positive_grade": labels[pos],
                    "negative_grade": labels[neg],
                    "sampler": name,
                    "mining": audits.get(neg),
                }
                for pos in positives
                for neg in chosen
            ]
        )
    return *variants, None


def load_sources():
    contract, rows, vectors = artifact_contract(INDEX)
    records = load_evidence(EVIDENCE, rows, contract["artifact_sha256"])
    cases = load_cases(TOPICS, topics=True)
    if len(cases) != 50 or len(rows) != 443:
        raise ValueError("frozen bounded 2022 diagnostic sources required")
    qrels = load_qrels(QRELS.read_bytes(), {c.case_id.split(":")[-1] for c in cases})
    return contract, rows, vectors, records, cases, qrels


def prepare(output, encoder):
    contract, rows, vectors, records, cases, qrels = load_sources()
    if encoder.metadata["snapshot_sha256"] != contract["snapshot_sha256"]:
        raise ValueError("mining query/document model mismatch")
    split = make_split(cases, records)
    output.mkdir(parents=True, exist_ok=False)
    protocol = {
        "version": VERSION,
        "created_at_utc": datetime.now(UTC).isoformat(),
        "parameters": PARAMETERS,
        "source_contract": contract,
        "encoder": encoder.metadata,
        "sources": {
            "topics": file_hash(TOPICS),
            "qrels": file_hash(QRELS),
            "evidence_manifest": file_hash(EVIDENCE / "manifest.json"),
        },
        "case_split": split["cases"],
        "trial_split": split["trials"],
        "implementation_sha256": file_hash(Path(__file__)),
        "limits": "Inspected 2022 cases and judgment-selected trial pool. "
        "Retrospective grouped split, not a new project holdout.",
    }
    write_json(output / "protocol.json", protocol)
    write_json(output / "split.json", split)
    encoded = encoder.encode([c.text for c in cases])
    query_vectors = {c.case_id: v for c, v in zip(cases, encoded.vectors, strict=True)}
    trial_ids = {r["trial_id"] for r in rows}
    labels, cross_partition = {p: {} for p in PARTITIONS}, 0
    for row in qrels:
        case_id = "trec-ct-2022:" + row["topic_id"]
        tid = row["trial_id"]
        if tid not in trial_ids:
            continue
        if split["cases"][case_id] != split["trials"][tid]:
            cross_partition += 1
            continue
        labels[split["cases"][case_id]].setdefault(case_id, {})[tid] = row["grade"]
    train_rows = [r for r in rows if split["trials"][r["trial_id"]] == "train"]
    lexical = SparseBM25([r["representations"]["title_conditions"] for r in train_rows])
    candidate_map = {p: {} for p in PARTITIONS}
    hard, random, skipped = [], [], []
    conditions = {tid: r["fields"]["conditions"]["normalized"] for tid, r in records.items()}
    for case in cases:
        cohort = split["cases"][case.case_id]
        scores = np.clip(vectors @ query_vectors[case.case_id], -1, 1)
        ranked = sorted(
            [
                (r["trial_id"], float(s))
                for r, s in zip(rows, scores, strict=True)
                if split["trials"][r["trial_id"]] == cohort
            ],
            key=lambda v: (-v[1], v[0]),
        )
        metadata = {r["trial_id"]: r["filter_metadata"] for r in rows}
        demographics = extract_topic_demographics(case.text)
        candidate_map[cohort][case.case_id] = [
            {"trial_id": tid, "score": score}
            for tid, score in ranked
            if not_deterministically_incompatible(demographics, metadata[tid])
        ][:100]
        if cohort != "train":
            continue
        query, _ = lexical.query(case.text)
        weights = dict(zip(query["indices"], query["values"], strict=True))
        lexical_scores = [
            sum(
                weights.get(i, 0.0) * value
                for i, value in zip(v["indices"], v["values"], strict=True)
            )
            for v in lexical.document_vectors
        ]
        bm25_ranked = sorted(
            [(r["trial_id"], float(s)) for r, s in zip(train_rows, lexical_scores, strict=True)],
            key=lambda v: (-v[1], v[0]),
        )
        h, r, skip = mine_pairs(
            case, labels["train"].get(case.case_id, {}), ranked, bm25_ranked, conditions
        )
        hard.extend(h)
        random.extend(r)
        if skip:
            skipped.append(skip)
    if len(hard) != len(random) or not hard:
        raise ValueError(
            "nonempty equal-budget hard/random training pairs required; do not reshuffle splits"
        )
    for cohort in PARTITIONS:
        write_json(
            output / f"cases-{cohort}.json",
            [c.model_dump(mode="json") for c in cases if split["cases"][c.case_id] == cohort],
        )
        write_json(output / f"labels-{cohort}.json", labels[cohort])
        write_json(output / f"candidates-{cohort}.json", candidate_map[cohort])
    write_json(output / "pairs-hard.json", hard)
    write_json(output / "pairs-random.json", random)
    write_json(output / "mining-skips.json", skipped)
    report = {
        "version": VERSION,
        "status": "complete",
        "parameters": PARAMETERS,
        "source_contract": contract,
        "sources": protocol["sources"],
        "implementation_sha256": file_hash(Path(__file__)),
        "statistics": {
            "cases": dict(Counter(split["cases"].values())),
            "trials": dict(Counter(split["trials"].values())),
            "labels": {p: sum(map(len, labels[p].values())) for p in PARTITIONS},
            "cross_partition_judgments_excluded": cross_partition,
            "hard_pairs": len(hard),
            "random_pairs": len(random),
            "training_cases_with_pairs": len({r["case_id"] for r in hard}),
            "positive_grades": dict(Counter(str(r["positive_grade"]) for r in hard)),
            "negative_grades": dict(Counter(str(r["negative_grade"]) for r in hard)),
            "skipped_training_cases": len(skipped),
        },
        "files": [file_record(p, output) for p in sorted(output.iterdir())],
    }
    write_json(output / "manifest.json", report)
    load_dataset(output)
    return report


def load_dataset(root, *, stage="verify"):
    if stage not in {"verify", "fit"}:
        raise ValueError("unsupported data access stage")
    manifest = json.loads((root / "manifest.json").read_bytes())
    required = {
        "protocol.json",
        "split.json",
        "pairs-hard.json",
        "pairs-random.json",
        "mining-skips.json",
    }
    required |= {
        f"{kind}-{p}.json" for p in PARTITIONS for kind in ("cases", "labels", "candidates")
    }
    if (
        manifest.get("status") != "complete"
        or manifest.get("version") != VERSION
        or manifest.get("parameters") != PARAMETERS
        or manifest.get("implementation_sha256") != file_hash(Path(__file__))
    ):
        raise ValueError("data protocol or mining implementation changed")
    verify_files(root, manifest["files"], required)
    # Fit can hash sealed test files, but cannot deserialize their cases/labels/rankings.
    data = {
        name[:-5]: json.loads((root / name).read_bytes())
        for name in required
        if stage != "fit" or not name.endswith("-test.json")
    }
    protocol, split = data["protocol"], data["split"]
    if not 1 <= len(split["cases"]) <= 100 or not 1 <= len(split["trials"]) <= 512:
        raise ValueError("bounded case/trial split required")
    if protocol["sources"] != manifest["sources"] or protocol["parameters"] != PARAMETERS:
        raise ValueError("data protocol differs from manifest")
    accessible = PARTITIONS if stage == "verify" else ("train", "dev")
    cases = [SyntheticCase.model_validate(c) for p in accessible for c in data[f"cases-{p}"]]
    if len({c.case_id for c in cases}) != len(cases):
        raise ValueError("duplicate synthetic cases")
    validate_split(split, set(split["cases"]), set(split["trials"]))
    if {c.case_id for c in cases} != {i for i, p in split["cases"].items() if p in accessible}:
        raise ValueError("cohort case inventory differs")
    if protocol["case_split"] != split["cases"] or protocol["trial_split"] != split["trials"]:
        raise ValueError("split differs from frozen protocol")
    for cohort in accessible:
        ids = {c["case_id"] for c in data[f"cases-{cohort}"]}
        if (
            any(split["cases"][i] != cohort for i in ids)
            or set(data[f"candidates-{cohort}"]) != ids
        ):
            raise ValueError("candidate cohort mismatch")
        for case_id, labels in data[f"labels-{cohort}"].items():
            if case_id not in ids or any(
                split["trials"].get(tid) != cohort
                or type(grade) is not int
                or grade not in {0, 1, 2}
                for tid, grade in labels.items()
            ):
                raise ValueError("label cohort or grade mismatch")
        for candidates in data[f"candidates-{cohort}"].values():
            tids = [r["trial_id"] for r in candidates]
            if (
                len(tids) != len(set(tids))
                or len(tids) > 100
                or any(
                    split["trials"].get(tid) != cohort or not np.isfinite(r["score"])
                    for tid, r in zip(tids, candidates, strict=True)
                )
            ):
                raise ValueError("candidate trial cohort mismatch")
    for sampler in ("hard", "random"):
        seen = set()
        for row in data[f"pairs-{sampler}"]:
            case_id, pos, neg = row["case_id"], row["positive_id"], row["negative_id"]
            key = (case_id, pos, neg)
            labels = data["labels-train"].get(case_id, {})
            if (
                key in seen
                or row["sampler"] != sampler
                or split["cases"].get(case_id) != "train"
                or any(split["trials"].get(tid) != "train" for tid in (pos, neg))
                or labels.get(pos) not in {1, 2}
                or labels.get(neg) != 0
                or row["positive_grade"] != labels[pos]
                or row["negative_grade"] != 0
            ):
                raise ValueError("training pair leakage or relevance-label mismatch")
            seen.add(key)
        if not seen:
            raise ValueError("empty training sampler")
    if {(r["case_id"], r["positive_id"]) for r in data["pairs-hard"]} != {
        (r["case_id"], r["positive_id"]) for r in data["pairs-random"]
    } or len(data["pairs-hard"]) != len(data["pairs-random"]):
        raise ValueError("training controls have different budgets or positives")
    return manifest, data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["prepare", "verify"])
    parser.add_argument("--data-id", type=local_id, default=DEFAULT_DATA)
    args = parser.parse_args()
    root = Path("data/processed") / args.data_id
    try:
        if args.command == "prepare":
            from pipelines.embeddings import MODELS, LocalSentenceEncoder

            report = prepare(root, LocalSentenceEncoder(MODELS["minilm"], Path("models")))
        else:
            report, _ = load_dataset(root)
        print(json.dumps({"status": "verified", "statistics": report["statistics"]}))
    except (ValueError, OSError, KeyError, TypeError, ImportError) as exc:
        parser.exit(
            1,
            f"Hard-negative data failed ({type(exc).__name__}); "
            "preserve outputs and check source contracts.\n",
        )


if __name__ == "__main__":
    main()
