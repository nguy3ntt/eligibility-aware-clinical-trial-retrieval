"""Review audit completeness, explicit non-clinical limits and integrity refusal."""

import json

import pytest

from evaluation import missing_information_review as audit


def test_authored_contract_report_covers_each_fixed_example():
    rows = audit.fixture_report()
    assert len(rows) == 21 and all(row["passed"] for row in rows)
    assert len({r["id"] for r in rows}) == 21
    assert all(r["plan"]["clinical_urgency"] is False for r in rows)
    assert all(r["plan"]["estimated_information_gain"] is None for r in rows)


@pytest.mark.parametrize("damage", ["identity", "status", "inventory"])
def test_audit_refuses_changed_identity_or_incomplete_report_before_reproduction(tmp_path, damage):
    report = {
        "version": audit.VERSION,
        "status": "complete",
        "identity": audit.identity(),
        "files": [],
    }
    if damage == "identity":
        report["identity"] = {}
    elif damage == "status":
        report["status"] = "failed"
    (tmp_path / "report.json").write_text(json.dumps(report))
    with pytest.raises(ValueError):
        audit.verify_report(tmp_path)
