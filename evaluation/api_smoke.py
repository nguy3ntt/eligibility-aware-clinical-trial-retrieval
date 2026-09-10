"""Real loopback HTTP verification against the prepared synthetic/public API catalog."""

import argparse
import json
import time
from pathlib import Path
from urllib.parse import urlparse

import httpx

from pipelines.connectors.snapshots import write_json
from pipelines.criteria.artifacts import file_hash, local_id


def verify_http(url):
    parsed = urlparse(url)
    if (
        parsed.scheme != "http"
        or parsed.hostname not in {"localhost", "127.0.0.1", "::1"}
        or parsed.username
        or parsed.password
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("only a plain loopback API URL is accepted")
    checks = []
    with httpx.Client(base_url=url, timeout=120, follow_redirects=False) as client:

        def call(method, path, expected=200, **kwargs):
            started = time.perf_counter()
            response = client.request(method, path, **kwargs)
            assert response.status_code == expected, (path, response.status_code)
            assert "INVENTED_PRIVATE_SENTINEL" not in response.text
            payload = response.json()
            checks.append(
                {
                    "method": method,
                    "path": path,
                    "status": response.status_code,
                    "seconds": time.perf_counter() - started,
                    "response": payload,
                }
            )
            return payload

        root = call("GET", "/")
        assert root["status"] == "bounded research API"
        assert call("GET", "/health")["status"] == "ok"
        assert call("GET", "/v1/ready")["status"] == "ready"
        assert call("GET", "/v1/cases?limit=2")["total"] == 51
        assert call("GET", "/v1/trials?limit=2")["total"] == 446
        assert call("GET", "/v1/cases/reranking-demo")["case"]["synthetic"] is True
        assert len(call("GET", "/v1/trials/NCT90009002")["criteria"]["criteria"]) == 3
        for trial_id, status in (
            ("NCT90009001", "insufficient_information"),
            ("NCT90009002", "potential_match"),
            ("NCT90009003", "likely_exclusion"),
        ):
            body = {"case_id": "reranking-demo", "trial_id": trial_id}
            packet = call("POST", "/v1/screening", json=body)
            assert packet["result"]["assessment"]["status"] == status
        repeated = call("POST", "/v1/screening", json=body)
        assert repeated["replayed"] and repeated["operation_id"] == packet["operation_id"]
        for method in ("dense", "sparse", "hybrid"):
            packet = call(
                "POST", "/v1/search", json={"case_id": "trec-ct-2022:29", "method": method}
            )
            assert len(packet["result"]["results"]) == 3
            assert packet["result"]["default_retrieval_changed"] is False
            if method == "dense":
                dense = packet
        assert [r["trial_id"] for r in dense["result"]["results"]] == [
            "NCT01726751",
            "NCT03325374",
            "NCT02749071",
        ]
        assert call("GET", "/v1/experiments/" + dense["operation_id"])["result"] == dense["result"]
        profiled = call(
            "POST", "/v1/search", json={"case_id": "trec-ct-2022:29", "fact_extractor": "profile"}
        )
        assert profiled["result"]["filter_plan"] is not None
        reranked = call(
            "POST",
            "/v1/search",
            json={"case_id": "trec-ct-2022:29", "rerank": True, "rerank_depth": 10},
        )
        assert reranked["result"]["reranker"]["revision"]
        assert all(
            r["screening"]["status"] == "insufficient_information"
            for r in reranked["result"]["results"]
        )
        nli = call(
            "POST",
            "/v1/screening",
            json={"case_id": "reranking-demo", "trial_id": "NCT90009001", "semantic": True},
        )
        assert all(a["promoted"] is False for a in nli["result"]["semantic"]["advisories"])
        experiment = call("POST", "/v1/experiments", json={})
        assert experiment["result"]["evaluation"]["exact_pairs"] == 34
        assert experiment["result"]["evaluation"]["criterion_count"] == 41
        call("GET", "/v1/cases/no-such-invented-case", 404)
        call(
            "POST",
            "/v1/search",
            422,
            json={"case_id": "reranking-demo", "text": "INVENTED_PRIVATE_SENTINEL"},
        )
        call("POST", "/v1/search", 422, json={"case_id": "reranking-demo", "top_k": 11})
        call("POST", "/v1/search", 413, content=b"x" * 17000)
        call("GET", "/health", 403, headers={"origin": "https://invalid.example"})
    return {
        "status": "passed",
        "checks": checks,
        "check_count": len(checks),
        "source": "verified synthetic catalog and public/invented trials only",
        "dense_operation_id": dense["operation_id"],
        "scope": "HTTP integration and engineering correctness, not clinical validation",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--output-id", type=local_id, required=True)
    args = parser.parse_args()
    output = Path("evaluation/reports") / args.output_id
    try:
        output.mkdir(parents=True, exist_ok=False)
    except OSError:
        parser.exit(1, "Use a fresh output ID.\n")
    try:
        result = verify_http(args.url)
        result["verifier_sha256"] = file_hash(Path(__file__))
        write_json(output / "http-checks.json", result)
        print(
            json.dumps({"status": "passed", "checks": result["check_count"], "report": str(output)})
        )
    except Exception as exc:
        write_json(output / "failure.json", {"status": "failed", "error_type": type(exc).__name__})
        parser.exit(
            1,
            f"HTTP verification failed ({type(exc).__name__}); inspect local service readiness.\n",
        )


if __name__ == "__main__":
    main()
