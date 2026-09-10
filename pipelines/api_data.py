"""Explicit migrations and immutable import of verified synthetic/public API catalogs."""

import argparse
import json
from pathlib import Path

from backend.app.core.config import get_settings
from backend.app.repositories.postgres import PostgresStore, digest, local_engine, migrate
from pipelines.connectors.synthetic_cases import load_cases
from pipelines.criteria.artifacts import file_hash, local_id


def seed(store, settings):
    from pipelines.indexing.hybrid import prepare_hybrid
    from pipelines.rerank import TOPICS, demo_data
    from pipelines.reranking_data import load_evidence

    index = Path(settings.processed_data_dir) / local_id(settings.api_index_id)
    contract, rows, _, _, _ = prepare_hybrid(index)
    evidence = Path(settings.processed_data_dir) / local_id(settings.api_evidence_id)
    records = load_evidence(evidence, rows, contract["artifact_sha256"])
    cases = {c.case_id: c.model_dump(mode="json") for c in load_cases(TOPICS, topics=True)}
    case, _, invented = demo_data()
    cases[case.case_id] = case.model_dump(mode="json")
    records.update(invented)
    catalog = {
        "schema_version": "api-catalog-v1",
        "contract": contract,
        "case_hashes": {key: digest(value) for key, value in cases.items()},
        "trial_hashes": {key: digest(value) for key, value in records.items()},
        "topics_sha256": file_hash(TOPICS),
        "evidence_manifest_sha256": file_hash(evidence / "manifest.json"),
        "scope": "public historical trial pool plus explicitly invented demonstration trials",
    }
    store.seed(catalog, cases, records)
    return {
        "status": "complete",
        "catalog_id": store.catalog_id,
        "cases": len(cases),
        "trials": len(records),
        "catalog_sha256": digest(catalog),
    }


def import_experiment(store, report_id):
    path = Path("evaluation/reports") / local_id(report_id) / "experiment.json"
    if path.stat().st_size > 5 * 1024**2:
        raise ValueError("experiment manifest exceeds import bound")
    report = json.loads(path.read_bytes())
    if report.get("status") not in {"complete", "passed"}:
        raise ValueError("only completed local experiment manifests may be imported")
    checksum = file_hash(path)
    operation_id = digest({"catalog": store.catalog_id, "report_id": report_id, "sha256": checksum})
    payload = {
        "operation_id": operation_id,
        "kind": "reviewed_experiment",
        "status": "complete",
        "source": {"report_id": report_id, "sha256": checksum},
        "result": report,
        "notice": "Historical recorded experiment; not a new clinical validation.",
    }
    store.save_operation(operation_id, "reviewed_experiment", payload["source"], payload)
    return {"status": "complete", "operation_id": operation_id}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("migrate", "seed", "status", "import-experiment"))
    parser.add_argument("--report-id", type=local_id)
    args = parser.parse_args()
    if args.command == "import-experiment" and not args.report_id:
        parser.error("import-experiment requires --report-id")
    settings = get_settings()
    engine = None
    try:
        engine = local_engine(settings.database_url)
        store = PostgresStore(engine, local_id(settings.api_catalog_id))
        if args.command == "migrate":
            migrate(engine)
            result = {"status": "complete", "revision": "0001_catalogs"}
        elif args.command == "seed":
            result = seed(store, settings)
        elif args.command == "import-experiment":
            result = import_experiment(store, args.report_id)
        else:
            result = store.ready()
        print(json.dumps(result, indent=2))
    except Exception as exc:
        parser.exit(
            1, f"API data operation failed ({type(exc).__name__}); no credentials/input echoed.\n"
        )
    finally:
        if engine is not None:
            engine.dispose()


if __name__ == "__main__":
    main()
