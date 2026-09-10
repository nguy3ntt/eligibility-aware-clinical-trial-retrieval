"""Reranking must preserve candidate membership, evidence and screening boundaries."""

import copy
import json
import os
import subprocess
import sys

import pytest

pytest.importorskip("numpy")

from backend.app.services.eligibility.rules import verify
from backend.app.services.explanations.evidence import explain_result, explain_screening
from backend.app.services.patient_extraction.extractor import extract_profile
from backend.app.services.retrieval.reranker import LocalReranker, reorder, validate_snapshot
from pipelines.criteria.parser import parse_eligibility
from pipelines.rerank import candidates, demo_data, explain
from pipelines.reranking_data import eligibility_source, from_xml, load_evidence, validate_record


def ranked():
    return [
        {"trial_id": f"NCT9000900{i}", "score": float(4 - i), "method": "exact_dense"}
        for i in range(1, 4)
    ]


def test_rerank_retains_tail_and_separate_scores():
    original = ranked()
    result = reorder(original, [{"score": -8.0}, {"score": 4.0}])
    assert [r["trial_id"] for r in result] == [original[i]["trial_id"] for i in (1, 0, 2)]
    assert result[0]["score"] == original[1]["score"]
    assert result[0]["original_rank"] == 2
    assert result[2]["reranker"] is None
    assert "reranker" not in original[0]


def test_reranking_ties_use_trial_id():
    original = ranked()[::-1]
    assert [r["trial_id"] for r in reorder(original, [{"score": 1.0}] * 3)] == [
        r["trial_id"] for r in ranked()
    ]


@pytest.mark.parametrize(
    "scores", [[], [{"score": float("nan")}], [{"score": float("inf")}], [{"score": 0.0}] * 4]
)
def test_bad_scores_rejected(scores):
    with pytest.raises(ValueError):
        reorder(ranked(), scores)


def test_duplicate_candidates_rejected():
    with pytest.raises(ValueError):
        reorder([ranked()[0]] * 2, [{"score": 0.0}])


def test_candidate_filter_preserves_unknowns_and_tail_ties():
    rows = [
        {"trial_id": str(i), "filter_metadata": {"sex": sex}}
        for i, sex in enumerate(("Male", "Female", "Unknown", None))
    ]
    results = candidates(rows, [1, 1, 1, 1], {"sex": "Male"})
    assert [r["trial_id"] for r in results] == ["0", "2", "3"]
    assert candidates(rows, [1, 1, 1, 1], {}, 2) == results[:1] + [
        {"trial_id": "1", "score": 1.0, "method": "exact_dense"}
    ]


@pytest.mark.parametrize(
    "scores,depth", [([1], 100), ([float("nan")] * 3, 100), ([1] * 3, 0), ([1] * 3, 101)]
)
def test_invalid_dense_candidates(scores, depth):
    _, _, records = demo_data()
    with pytest.raises(ValueError):
        candidates([r["row"] for r in records.values()], scores, {}, depth)


def test_demo_has_all_three_honest_trial_statuses():
    case, ranking, records = demo_data()
    outputs = explain(case, ranking, records, 3)
    assert [o["eligibility_assessment"] for o in outputs] == [
        "insufficient_information",
        "potential_match",
        "likely_exclusion",
    ]
    for result in outputs:
        assert result["relevance"]["fields"]
        for criterion in result["screening"]["criteria"]:
            assert criterion["trial_evidence"]["text"]
            if criterion["outcome"] != "unknown":
                assert criterion["patient_facts"]
        assert "not confirmed medical eligibility" in result["notice"]


def test_explanations_do_not_claim_unperformed_screening():
    case, ranking, records = demo_data()
    result = explain_result(case, ranking[0], records[ranking[0]["trial_id"]])
    assert result["screening"] is None
    assert result["eligibility_assessment"] == "not_performed"


@pytest.mark.parametrize("mutation", ["normalized", "original_texts", "locator", "trial_id"])
def test_field_tampering_rejected(mutation):
    _, _, records = demo_data()
    record = copy.deepcopy(next(iter(records.values())))
    if mutation == "trial_id":
        record["trial_id"] = "NCT90009999"
    else:
        record["fields"]["brief_title"][mutation] = (
            ["changed"] if mutation == "original_texts" else "changed"
        )
    with pytest.raises(ValueError):
        validate_record(record)


def test_xml_must_reproduce_retrieved_row():
    _, _, records = demo_data()
    row = next(iter(records.values()))["row"]
    with pytest.raises(ValueError):
        from_xml(
            b"<clinical_study><id_info><nct_id>NCT90009001</nct_id></id_info></clinical_study>", row
        )
    with pytest.raises(ValueError):
        from_xml(b"<!DOCTYPE x><clinical_study/>", row)


def test_stored_screening_forgery_rejected():
    case, _, records = demo_data()
    record = records["NCT90009003"]
    assessment = verify(extract_profile(case), parse_eligibility(eligibility_source(record)))
    changed = assessment.model_copy(update={"status": "potential_match"})
    with pytest.raises(ValueError):
        explain_screening(changed)


def test_cross_case_and_trial_screening_rejected():
    case, ranking, records = demo_data()
    assessment = verify(
        extract_profile(case), parse_eligibility(eligibility_source(records["NCT90009002"]))
    )
    with pytest.raises(ValueError):
        explain_result(case, ranking[0], records["NCT90009001"], assessment)
    with pytest.raises(ValueError):
        explain_result(
            case.model_copy(update={"text": "50-year-old man."}),
            ranking[1],
            records["NCT90009002"],
            assessment,
        )


def test_reranker_input_hash_tampering_rejected():
    case, ranking, records = demo_data()
    result = {
        **ranking[0],
        "reranker": {
            "input": {"query": {"source_sha256": "0" * 64, "start": 0, "end": 1, "text": "4"}}
        },
    }
    with pytest.raises(ValueError):
        explain_result(case, result, records[result["trial_id"]])


def test_bad_evidence_artifact_rejected(tmp_path):
    (tmp_path / "manifest.json").write_text(json.dumps({"status": "failed"}))
    with pytest.raises(ValueError):
        load_evidence(tmp_path, [], "0" * 64)


def test_incomplete_model_rejected(tmp_path):
    (tmp_path / "snapshot.json").write_text(json.dumps({"status": "failed"}))
    with pytest.raises(ValueError):
        validate_snapshot(tmp_path)


@pytest.mark.parametrize(
    "arguments",
    [["demo", "--depth", "51"], ["demo", "--top-k", "0"], ["demo", "--output-id", "../escape"]],
)
def test_cli_rejects_unbounded_or_unsafe_requests(arguments):
    result = subprocess.run(
        [sys.executable, "-m", "pipelines.rerank", *arguments], capture_output=True, text=True
    )
    assert result.returncode != 0


def test_cli_demo_without_model():
    result = subprocess.run(
        [sys.executable, "-m", "pipelines.rerank", "demo", "--no-rerank"],
        capture_output=True,
        text=True,
        check=True,
    )
    data = json.loads(result.stdout)
    assert data["reranker"] is None
    assert data["candidate_count"] == 3
    assert data["default_retrieval_changed"] is False


@pytest.mark.skipif(
    os.environ.get("RUN_RERANKER_TESTS") != "1", reason="explicit local model opt-in"
)
def test_real_reranker_replay_relevance_and_truncation():
    model = LocalReranker()
    case, ranking, records = demo_data()
    docs = [records[r["trial_id"]]["row"]["representations"]["summary"] for r in ranking]
    scored = model.score(case, docs)
    # Independently use the tokenizer's normal pair template on these untruncated examples.
    import torch

    direct = model.tokenizer([case.text] * len(docs), docs, padding=True, return_tensors="pt")
    with torch.inference_mode():
        reference = model.model(**direct).logits[:, 0].tolist()
    assert [s["score"] for s in scored] == reference
    assert model.score(case, docs) == scored
    assert scored[1]["score"] > scored[0]["score"]
    output = explain(case, reorder(ranking, scored), records, 3)
    assert {o["trial_id"] for o in output} == set(records)
    extended = case.model_copy(update={"text": "asthma " * 1000})
    truncated = model.score(extended, ["asthma " * 1000])[0]
    assert truncated["input"]["query"]["truncated"]
    assert truncated["input"]["document"]["truncated"]
    assert sum(s["used_tokens"] for s in truncated["input"].values()) + 3 == 512
    with pytest.raises(ValueError):
        model.score(case.model_copy(update={"synthetic": False}), docs)
    for invalid in ([], [""], [docs[0]] * 51):
        with pytest.raises(ValueError):
            model.score(case, invalid)


def test_candidate_scores_and_count_are_bounded():
    original = ranked()
    original[0]["score"] = float("nan")
    with pytest.raises(ValueError):
        reorder(original, [{"score": 1}])
    with pytest.raises(ValueError):
        reorder([{"trial_id": str(i), "score": 1} for i in range(101)], [{"score": 1}])


@pytest.mark.parametrize("change", ["hash", "span", "count", "truncation", "method", "score"])
def test_explanation_rejects_invalid_stored_model_evidence(change):
    from backend.app.schemas.patient import text_hash

    case, ranking, records = demo_data()
    record = records[ranking[0]["trial_id"]]
    model_result = {"score": 0.5, "method": "learned_cross_encoder", "input": {}}
    for key, text in (
        ("query", case.text),
        ("document", record["row"]["representations"]["summary"]),
    ):
        model_result["input"][key] = {
            "source_sha256": text_hash(text),
            "start": 0,
            "end": len(text),
            "text": text,
            "used_tokens": 20,
            "total_tokens": 20,
            "truncated": False,
        }
    if change == "hash":
        model_result["input"]["query"]["source_sha256"] = "0" * 64
    elif change == "span":
        model_result["input"]["query"]["text"] = "changed"
    elif change == "count":
        model_result["input"]["query"]["used_tokens"] = 500
    elif change == "truncation":
        model_result["input"]["query"]["truncated"] = True
    elif change == "method":
        model_result["method"] = "deterministic_rule"
    else:
        model_result["score"] = float("nan")
    with pytest.raises(ValueError):
        explain_result(case, {**ranking[0], "reranker": model_result}, record)


def test_completed_report_is_never_overwritten(tmp_path, monkeypatch, capsys):
    from pipelines.rerank import main

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["rerank", "demo", "--no-rerank", "--output-id", "safe"])
    main()
    saved = tmp_path / "evaluation/reports/safe/results.json"
    before = saved.read_bytes()
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 1
    assert saved.read_bytes() == before
    assert not (saved.parent / "failure.json").exists()


def test_prefix_reordering_cannot_change_recall_at_100():
    from evaluation.metrics.retrieval import query_metrics

    original = ranked()
    changed = reorder(original, [{"score": 0}, {"score": 1}])
    labels = {r["trial_id"]: (2 if i == 0 else 0) for i, r in enumerate(original)}
    before = query_metrics([r["trial_id"] for r in original], labels)
    after = query_metrics([r["trial_id"] for r in changed], labels)
    assert after["recall_at_100"] == before["recall_at_100"]
    assert after["ndcg_at_10"] < before["ndcg_at_10"]
