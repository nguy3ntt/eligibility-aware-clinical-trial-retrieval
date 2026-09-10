"""Bounded synchronous API orchestration over verified PostgreSQL and Qdrant evidence."""

import threading
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from backend.app.core.errors import ServiceError
from backend.app.repositories.postgres import EvidenceError, digest
from backend.app.schemas.api import OperationResponse
from backend.app.schemas.patient import SyntheticCase
from backend.app.services.eligibility.rules import verify
from backend.app.services.explanations.evidence import explain_result, explain_screening
from backend.app.services.patient_extraction.extractor import extract_profile
from pipelines.criteria.artifacts import file_hash, local_id
from pipelines.criteria.parser import parse_eligibility
from pipelines.reranking_data import eligibility_source, validate_record


def implementation():
    # Hash executable dependencies, not private tracking or generated outputs.
    root = Path(__file__).resolve().parents[3]
    paths = sorted(
        {
            p
            for folder in ("backend/app", "pipelines", "evaluation")
            for p in (root / folder).rglob("*.py")
            if "tests" not in p.parts and not p.name.startswith("milestone")
        }
    )
    return {p.relative_to(root).as_posix(): file_hash(p) for p in paths}


class ResearchService:
    def __init__(self, store, settings):
        self.store, self.settings = store, settings
        self.lock = threading.Lock()
        self.encoder = self.reranker = self.nli = self.prepared = None
        self.code = implementation()
        self.versions = {}
        for name in (
            "fastapi",
            "pydantic",
            "sqlalchemy",
            "psycopg",
            "torch",
            "transformers",
            "numpy",
        ):
            try:
                self.versions[name] = version(name)
            except PackageNotFoundError:
                self.versions[name] = "not_installed"

    def catalog(self):
        catalog = self.store.catalog()
        if catalog is None:
            raise ServiceError(
                503, "catalog_unavailable", "Migrate and import the verified catalog first."
            )
        if catalog.get("schema_version") != "api-catalog-v1":
            raise EvidenceError("unsupported catalog")
        return catalog

    def record(self, kind, record_id):
        catalog = self.catalog()
        hashes = catalog["case_hashes" if kind == "cases" else "trial_hashes"]
        if record_id not in hashes:
            raise ServiceError(404, "not_found", "The requested catalog record does not exist.")
        result = self.store.get(kind, record_id)
        if result is None or digest(result) != hashes[record_id]:
            raise EvidenceError("catalog/source mismatch")
        if kind == "cases":
            case = SyntheticCase.model_validate(result)
            if case.case_id != record_id:
                raise EvidenceError("synthetic case identity mismatch")
        else:
            validate_record(result)
            if result["trial_id"] != record_id:
                raise EvidenceError("trial identity mismatch")
        return result

    def page(self, kind, limit, offset):
        catalog = self.catalog()
        page = self.store.page(kind, limit, offset)
        if kind != "operations" and page["total"] != len(
            catalog["case_hashes" if kind == "cases" else "trial_hashes"]
        ):
            raise EvidenceError("catalog record count changed")
        items = []
        for entry in page["items"]:
            record_id = entry["id"]
            if kind == "operations":
                payload = entry["payload"]
                items.append(
                    {
                        "operation_id": record_id,
                        "kind": payload["kind"],
                        "status": payload["status"],
                    }
                )
            else:
                payload = self.record(kind, record_id)
                if kind == "cases":
                    items.append(
                        {"case_id": record_id, "synthetic": True, "source": payload["source"]}
                    )
                else:
                    items.append(
                        {
                            "trial_id": record_id,
                            "source_kind": payload["source_kind"],
                            "title": payload["fields"]["brief_title"]["normalized"],
                        }
                    )
        return {**page, "items": items}

    def readiness(self):
        from backend.app.repositories.qdrant import QdrantRepository

        database = self.store.ready()
        with QdrantRepository(self.settings.qdrant_url, self.settings.api_collection) as repo:
            repo.check_contract(self.catalog()["contract"])
        return {
            "status": "ready",
            "postgres": database,
            "qdrant": "ready",
            "model_loading": "lazy_on_first_search",
            "catalog_id": self.store.catalog_id,
        }

    def execute(self, kind, request):
        if not self.lock.acquire(blocking=False):
            raise ServiceError(429, "busy", "A bounded operation is running; retry shortly.")
        try:
            catalog = self.catalog()
            parameters = request.model_dump(mode="json")
            provenance = {
                "catalog_id": self.store.catalog_id,
                "catalog_sha256": digest(catalog),
                "implementation_sha256": digest(self.code),
                "code_sha256": self.code,
                "runtime_versions": self.versions,
                "retrieval_configuration": {
                    "collection": self.settings.api_collection,
                    "index_id": self.settings.api_index_id,
                    "evidence_id": self.settings.api_evidence_id,
                },
            }
            # Changing fixture labels cannot reuse old results.
            if kind == "experiment":
                from pipelines.screening_data import DEFAULT_FIXTURE

                provenance["fixture_sha256"] = file_hash(DEFAULT_FIXTURE)
            operation_id = digest({"kind": kind, "request": parameters, "provenance": provenance})
            cached = self.store.get("operations", operation_id)
            if cached is not None:
                result = OperationResponse.model_validate(cached)
                if result.operation_id != operation_id or result.request != parameters:
                    raise EvidenceError("stored operation identity mismatch")
                return result.model_copy(update={"replayed": True})
            result = getattr(self, kind)(request)
            packet = OperationResponse(
                operation_id=operation_id,
                kind=kind,
                request=parameters,
                result=result,
                provenance=provenance,
            )
            self.store.save_operation(
                operation_id, kind, parameters, packet.model_dump(mode="json")
            )
            return packet
        finally:
            self.lock.release()

    def screening(self, request):
        case = SyntheticCase.model_validate(self.record("cases", request.case_id))
        trial = self.record("trials", request.trial_id)
        assessment = verify(extract_profile(case), parse_eligibility(eligibility_source(trial)))
        result = {
            "assessment": assessment.model_dump(mode="json"),
            "explanation": explain_screening(assessment),
            "semantic": None,
        }
        if request.semantic:
            from backend.app.services.eligibility.semantic import LocalNLI, advise

            if self.nli is None:
                self.nli = LocalNLI()
            result["semantic"] = advise(assessment, self.nli)
        return result

    def search(self, request):
        from backend.app.repositories.qdrant import QdrantRepository
        from backend.app.services.patient_extraction.filters import build_filter_plan
        from backend.app.services.retrieval.hybrid import rank_results, search_branches
        from backend.app.services.retrieval.reranker import LocalReranker, reorder
        from evaluation.baselines.filters import extract_topic_demographics
        from pipelines.embeddings import MODELS, LocalSentenceEncoder
        from pipelines.indexing.hybrid import prepare_hybrid, verify_hybrid

        case = SyntheticCase.model_validate(self.record("cases", request.case_id))
        if self.prepared is None:
            self.prepared = prepare_hybrid(
                Path(self.settings.processed_data_dir) / local_id(self.settings.api_index_id)
            )
        contract, rows, _, lexical, points = self.prepared
        if contract != self.catalog()["contract"]:
            raise EvidenceError("PostgreSQL catalog and retrieval artifact disagree")
        if self.encoder is None:
            self.encoder = LocalSentenceEncoder(MODELS["minilm"], Path("models"))
        if self.encoder.metadata["snapshot_sha256"] != contract["snapshot_sha256"]:
            raise EvidenceError("query encoder differs from catalog")
        profile = extract_profile(case)
        plan = build_filter_plan(profile) if request.fact_extractor == "profile" else None
        facts = plan["demographics"] if plan else extract_topic_demographics(case.text)
        if request.filter == "none":
            facts = None
        encoded = self.encoder.encode([case.text])
        with QdrantRepository(self.settings.qdrant_url, self.settings.api_collection) as repo:
            # The bounded API verifies all stored vectors/payloads before returning fresh results.
            verify_hybrid(repo, contract, points)
            branches, audit = search_branches(
                repo, contract, lexical, encoded.vectors[0].tolist(), case.text, demographics=facts
            )
        ranking = rank_results(branches, method=request.method, k=100)
        model = None
        if request.rerank and ranking:
            if self.reranker is None:
                self.reranker = LocalReranker()
            documents = [
                self.record("trials", r["trial_id"])["row"]["representations"]["summary"]
                for r in ranking[: request.rerank_depth]
            ]
            ranking = reorder(ranking, self.reranker.score(case, documents))
            model = self.reranker.metadata
        else:
            ranking = [
                {**r, "rank": i + 1, "original_rank": i + 1, "reranker": None}
                for i, r in enumerate(ranking)
            ]
        results = []
        expected_rows = {r["trial_id"]: r for r in rows}
        for item in ranking[: request.top_k]:
            record = self.record("trials", item["trial_id"])
            if record["row"] != expected_rows[item["trial_id"]]:
                raise EvidenceError("retrieved trial differs from source row")
            assessment = verify(profile, parse_eligibility(eligibility_source(record)))
            results.append(explain_result(case, item, record, assessment))
        return {
            "method": request.method,
            "filter": request.filter,
            "fact_extractor": request.fact_extractor,
            "filter_facts": facts,
            "filter_plan": plan,
            "dense_mode": "exact",
            "contract": contract,
            "encoder": self.encoder.metadata,
            "reranker": model,
            "lexical_query": audit,
            "candidate_count": len(ranking),
            "query_truncated": encoded.token_counts[0] > self.encoder.spec.max_tokens,
            "results": results,
            "benchmark_comparable": False,
            "semantic_promotion": False,
            "default_retrieval_changed": False,
        }

    def experiment(self, request):
        from evaluation.screening import evaluate_fixture
        from pipelines.screening_data import DEFAULT_FIXTURE

        result = evaluate_fixture()
        return {
            "configuration": request.configuration,
            "fixture_sha256": file_hash(DEFAULT_FIXTURE),
            "status": "passed" if result["exact_pairs"] == result["pairs"] else "failed",
            "evaluation": result,
            "clinical_validation": False,
        }
