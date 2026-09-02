"""Tiny synthetic tests for rendering, filtering, metrics, and BM25 runs."""

import json
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from evaluation.baselines import bm25
from evaluation.baselines.filters import (
    extract_topic_demographics,
    not_deterministically_incompatible,
)
from evaluation.error_analysis import build_worksheet
from evaluation.metrics.retrieval import aggregate_metrics, query_metrics
from pipelines.connectors.snapshots import sha256, write_json
from pipelines.render_trials import REPRESENTATIONS, VERSION, render_trial


def synthetic_trial(trial_id: str, condition: str, sex: str = "All") -> ET.Element:
    return ET.fromstring(
        f"""<clinical_study>
<id_info><nct_id>{trial_id}</nct_id></id_info>
<brief_title>{condition} research</brief_title>
<brief_summary><textblock>Study of {condition}.</textblock></brief_summary>
<condition>{condition}</condition>
<intervention><intervention_name>Invented intervention</intervention_name></intervention>
<eligibility><criteria><textblock>Adults with {condition}.</textblock></criteria>
<gender>{sex}</gender><minimum_age>18 Years</minimum_age><maximum_age>80 Years</maximum_age>
</eligibility>
</clinical_study>"""
    )


def rendered(trial_id: str, condition: str, sex: str = "All") -> dict:
    return render_trial(
        synthetic_trial(trial_id, condition, sex),
        {"archive": "fixture.zip", "member": f"{trial_id}.xml", "crc32": "00000000"},
    )


def test_renderer_versions_field_combinations_and_source_evidence() -> None:
    row = rendered("NCT00000001", "invented asthma")
    assert row["renderer_version"] == VERSION
    assert set(row["representations"]) == set(REPRESENTATIONS)
    assert "Invented intervention" not in row["representations"]["title_conditions"]
    assert "Invented intervention" in row["representations"]["summary"]
    assert "Adults with invented asthma" in row["representations"]["eligibility"]
    assert row["filter_metadata"] == {
        "sex": "All",
        "minimum_age": "18 Years",
        "maximum_age": "80 Years",
    }
    assert len(row["content_sha256"]) == 64
    assert row["source"]["member"] == "NCT00000001.xml"


def test_demographic_filter_removes_only_explicit_contradictions() -> None:
    topic = extract_topic_demographics("A 25-year-old woman with an invented condition.")
    assert topic["sex"] == "Female"
    assert topic["age_days"] == pytest.approx(25 * 365.2425)
    assert not_deterministically_incompatible(
        topic, {"sex": None, "minimum_age": None, "maximum_age": None}
    )
    assert not not_deterministically_incompatible(
        topic, {"sex": "Male", "minimum_age": "18 Years", "maximum_age": "80 Years"}
    )
    assert not not_deterministically_incompatible(
        topic, {"sex": "All", "minimum_age": "30 Years", "maximum_age": None}
    )
    compact = extract_topic_demographics("A 75F with an invented condition.")
    assert compact["sex"] == "Female" and compact["age_days"] == pytest.approx(75 * 365.2425)
    later_reference = extract_topic_demographics(
        "A 32-year-old woman with an invented condition. "
        + "Unrelated history " * 30
        + "Her father is male."
    )
    assert later_reference["sex"] == "Female"
    assert later_reference["sex_ambiguous"] is False


def test_retrieval_metrics_use_graded_ndcg_and_binary_recall() -> None:
    metrics = query_metrics(
        ["NCT00000002", "NCT00000001", "NCT00000003"],
        {"NCT00000001": 2, "NCT00000002": 1, "NCT00000003": 0},
    )
    assert 0 < metrics["ndcg_at_5"] < 1
    assert metrics["mrr"] == 1
    assert metrics["precision_at_10"] == 0.2
    assert metrics["recall_at_100"] == 1
    assert aggregate_metrics({"1": metrics, "2": metrics}) == metrics


def test_tiny_bm25_experiment_writes_ranked_runs_and_metrics(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pytest.importorskip("bm25s")
    documents = tmp_path / "documents"
    documents.mkdir()
    rows = [
        rendered("NCT00000001", "invented asthma", "Female"),
        rendered("NCT00000002", "invented diabetes"),
        rendered("NCT00000003", "invented migraine"),
    ]
    document_path = documents / "documents.jsonl"
    document_path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows), encoding="utf-8"
    )
    write_json(
        documents / "manifest.json",
        {
            "status": "complete",
            "files": [{"path": "documents.jsonl", "sha256": sha256(document_path.read_bytes())}],
        },
    )
    topics = tmp_path / "topics.xml"
    topics.write_text(
        """<topics task="2022 TREC Clinical Trials">
<topic number="1">A 30-year-old woman with invented asthma.</topic>
<topic number="2">A 50-year-old man with invented diabetes.</topic>
</topics>""",
        encoding="utf-8",
    )
    qrels = tmp_path / "qrels.txt"
    qrels.write_text("1 0 NCT00000001 2\n2 0 NCT00000002 2\n", encoding="utf-8")
    monkeypatch.setitem(bm25.PARAMETERS, "run_depth", 3)
    result = bm25.run_experiment(documents, topics, qrels, tmp_path / "report")
    assert result["status"] == "complete"
    assert result["selected_run"] in {
        f"{representation}-{filter_name}"
        for representation in REPRESENTATIONS
        for filter_name in ["none", "age_sex"]
    }
    run_lines = (tmp_path / "report/title_conditions-none.run").read_text().splitlines()
    assert len(run_lines) == 6
    assert all(len(line.split()) == 6 for line in run_lines)

    worksheet = build_worksheet(
        document_path,
        tmp_path / "report/title_conditions-none.run",
        tmp_path / "report/title_conditions-none-metrics.json",
        topics,
        qrels,
        tmp_path / "worksheet.json",
        count=1,
        depth=2,
    )
    assert worksheet["status"] == "pending_review"
    assert len(worksheet["queries"]) == 2
    assert all(query["synthetic"] for query in worksheet["queries"])
    assert all(len(query["ranked_trials"]) == 2 for query in worksheet["queries"])
