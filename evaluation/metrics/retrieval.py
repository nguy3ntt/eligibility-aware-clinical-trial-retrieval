"""Deterministic graded retrieval metrics with explicit cutoffs."""

from __future__ import annotations

import math
from collections.abc import Iterable


def _dcg(grades: Iterable[int]) -> float:
    return sum(grade / math.log2(rank + 1) for rank, grade in enumerate(grades, 1))


def query_metrics(ranking: list[str], judgments: dict[str, int]) -> dict[str, float]:
    relevant = {trial_id for trial_id, grade in judgments.items() if grade > 0}
    eligible = {trial_id for trial_id, grade in judgments.items() if grade == 2}
    excluded = {trial_id for trial_id, grade in judgments.items() if grade == 1}

    def ndcg(cutoff: int) -> float:
        actual = [judgments.get(trial_id, 0) for trial_id in ranking[:cutoff]]
        ideal = sorted(judgments.values(), reverse=True)[:cutoff]
        denominator = _dcg(ideal)
        return _dcg(actual) / denominator if denominator else 0.0

    first_relevant = next(
        (rank for rank, trial_id in enumerate(ranking, 1) if trial_id in relevant), None
    )
    retrieved_10 = ranking[:10]
    retrieved_100 = set(ranking[:100])
    return {
        "ndcg_at_5": ndcg(5),
        "ndcg_at_10": ndcg(10),
        "mrr": 1.0 / first_relevant if first_relevant else 0.0,
        "precision_at_10": sum(trial_id in relevant for trial_id in retrieved_10) / 10,
        "recall_at_100": len(retrieved_100 & relevant) / len(relevant) if relevant else 0.0,
        "success_at_5": float(any(trial_id in relevant for trial_id in ranking[:5])),
        "eligible_recall_at_100": (
            len(retrieved_100 & eligible) / len(eligible) if eligible else 0.0
        ),
        "excluded_recall_at_100": (
            len(retrieved_100 & excluded) / len(excluded) if excluded else 0.0
        ),
    }


def aggregate_metrics(per_query: dict[str, dict[str, float]]) -> dict[str, float]:
    if not per_query:
        raise ValueError("cannot aggregate an empty query set")
    names = next(iter(per_query.values())).keys()
    return {
        name: sum(values[name] for values in per_query.values()) / len(per_query) for name in names
    }
