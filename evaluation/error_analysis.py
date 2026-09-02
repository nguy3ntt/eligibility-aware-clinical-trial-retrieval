"""Build a local evidence worksheet for manual BM25 query error analysis."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from pipelines.connectors.snapshots import write_json
from pipelines.connectors.trec import LABELS, load_qrels, load_topics


def build_worksheet(
    documents_path: Path,
    run_path: Path,
    metrics_path: Path,
    topics_path: Path,
    qrels_path: Path,
    output: Path,
    *,
    count: int = 5,
    depth: int = 10,
) -> dict[str, object]:
    metrics = json.loads(metrics_path.read_bytes())["per_query"]
    ordered = sorted(metrics, key=lambda topic_id: metrics[topic_id]["ndcg_at_10"])
    selected = ordered[:count] + ordered[-count:][::-1]
    groups = {topic_id: "lowest" for topic_id in ordered[:count]}
    groups.update({topic_id: "highest" for topic_id in ordered[-count:]})

    topics = {topic["topic_id"]: topic for topic in load_topics(topics_path.read_bytes())}
    qrels = load_qrels(qrels_path.read_bytes(), set(topics))
    judgments = {(row["topic_id"], row["trial_id"]): row for row in qrels}
    rankings: dict[str, list[dict[str, object]]] = {topic_id: [] for topic_id in selected}
    with run_path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            topic_id, _, trial_id, rank, score, run_name = line.split()
            if topic_id in rankings and int(rank) <= depth:
                judgment = judgments.get((topic_id, trial_id))
                rankings[topic_id].append(
                    {
                        "trial_id": trial_id,
                        "rank": int(rank),
                        "score": float(score),
                        "run_name": run_name,
                        "run_line": line_number,
                        "source_grade": judgment["grade"] if judgment else None,
                        "source_label": LABELS[judgment["grade"]] if judgment else "unjudged",
                    }
                )
    wanted = {row["trial_id"] for rows in rankings.values() for row in rows}
    documents = {}
    with documents_path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            row = json.loads(line)
            if row["trial_id"] in wanted:
                documents[row["trial_id"]] = {
                    "document_line": line_number,
                    "title_conditions": row["representations"]["title_conditions"],
                    "summary_excerpt": row["representations"]["summary"][:500],
                    "content_sha256": row["content_sha256"],
                    "source": row["source"],
                }
                if len(documents) == len(wanted):
                    break
    missing = sorted(wanted - documents.keys())
    if missing:
        raise ValueError(f"ranked documents missing from rendered corpus: {len(missing)}")
    worksheet = {
        "status": "pending_review",
        "run": run_path.name,
        "selection": {
            "metric": "ndcg_at_10",
            "lowest": ordered[:count],
            "highest": ordered[-count:][::-1],
            "depth": depth,
        },
        "queries": [],
    }
    for topic_id in selected:
        worksheet["queries"].append(
            {
                "topic_id": topic_id,
                "group": groups[topic_id],
                "synthetic": True,
                "synthetic_case_text": topics[topic_id]["text"],
                "metrics": metrics[topic_id],
                "ranked_trials": [
                    {**ranked, "document": documents[ranked["trial_id"]]}
                    for ranked in rankings[topic_id]
                ],
                "review_status": "pending",
                "observation": None,
            }
        )
    write_json(output, worksheet)
    return worksheet


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--documents", type=Path, required=True)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--metrics", type=Path, required=True)
    parser.add_argument("--topics", type=Path, required=True)
    parser.add_argument("--qrels", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = build_worksheet(
        args.documents,
        args.run,
        args.metrics,
        args.topics,
        args.qrels,
        args.output,
    )
    print(json.dumps({"status": result["status"], "queries": len(result["queries"])}))


if __name__ == "__main__":
    main()
