from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("bm25s")

from evaluation import release_benchmark as release


def test_cutoff_ties_and_filtered_high_scores_follow_stable_ids():
    scores = np.array([0.5, 0.9, 0.5, 0.5, 0.1])
    ids = np.array(["C", "Z", "B", "A", "D"])
    allowed = np.array([True, False, True, True, True])
    assert release.top_indices(scores, ids, allowed, depth=2).tolist() == [3, 2]
    assert release.top_indices(np.zeros(5), ids, allowed, positive=True).size == 0


def test_nonfinite_scores_and_unpaired_topics_are_rejected():
    with pytest.raises(ValueError, match="finite"):
        release.top_indices(np.array([np.nan]), np.array(["A"]), np.array([True]))
    with pytest.raises(ValueError, match="paired"):
        release.paired_interval({"1": {}}, {"2": {}})


def test_bootstrap_keeps_negative_results_and_is_reproducible():
    a = {str(i): {"ndcg_at_10": 0.7} for i in range(5)}
    b = {str(i): {"ndcg_at_10": 0.4} for i in range(5)}
    report = release.paired_interval(a, b)
    assert report == release.paired_interval(a, b)
    assert report["ci95"] == pytest.approx([-0.3, -0.3])
    assert report["held_out"] is False


def test_bounded_diagnostic_cannot_be_reported_as_full_benchmark(monkeypatch, tmp_path):
    monkeypatch.setattr(release, "verify_index", lambda _root: {"documents": 443})
    with pytest.raises(ValueError, match="full frozen corpus"):
        release.run(*([Path("unused")] * 5), tmp_path / "output")
    assert not (tmp_path / "output").exists()
