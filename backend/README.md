# Backend

The local research API exposes curated synthetic cases, trial evidence, search, screening and saved experiments through `/v1`. [The API guide](../docs/local-research-api.md) includes startup, request contracts and manual checks. The Qdrant boundary remains loopback-only and validates artifact/model contracts; PostgreSQL stores immutable source catalogs and complete evidence packets. Source ingestion stays in pipelines.

The backend orchestrates existing services without notebook state. `services/application.py` preserves retrieval defaults, bounds expensive operations and records reproducible request identities. `api/boundary.py` limits bodies, rejects remote Host/Origin values and prevents failures from echoing inputs or logging exceptions with sensitive details. No arbitrary patient-text entry point is accepted.

`services/retrieval/sparse.py` implements versioned corpus-fitted BM25 vectors; `hybrid.py` runs matched dense/sparse branches and deterministic RRF with raw-score/rank/evidence provenance. Qdrant's metadata contract prevents mixing lexical vocabularies or artifacts. These are reusable internal services; the [hybrid CLI guide](../docs/hybrid-retrieval.md) exposes the current research workflow while the API composes the same services without making clinical decisions.

`schemas/patient.py` defines validated immutable synthetic cases, facts, source spans, and profiles. `services/patient_extraction/` contains versioned bounded rules and a conservative filter builder that revalidates profile values/evidence before use. Only age/sex may constrain retrieval; other facts remain evidence for later criterion work. The [fact guide](../docs/patient-facts.md) documents coverage, uncertainty, and the explicit profile search option. The case endpoint exposes this profile without making medical eligibility decisions.

`schemas/criteria.py` defines lossless source, section and criterion contracts. `repositories/criteria.py` reuses the loopback Qdrant transport for a separate immutable criterion artifact contract, named dense/sparse vectors, safe loading and exact bounded queries. Parsing remains in pipelines. The [criterion guide](../docs/eligibility-parsing.md) describes the internal contracts and CLI; trial lookup exposes the parse and screening composes the separate verification service.

`schemas/eligibility.py` defines evidence-backed criterion and trial screening packets. `services/eligibility/rules.py` checks whole supported clauses, validates current source-derived facts/parses and exposes `validate_assessment` to reproduce stored decisions. `semantic.py` provides pinned local NLI advisories that never change screening status. Missing or unsupported evidence stays unknown. See [screening behavior and manual checks](../docs/eligibility-verification.md); the API reuses these services without making medical decisions.

The optional `services/retrieval/reranker.py` scores bounded query/summary pairs using a pinned local cross-encoder. `services/explanations/evidence.py` produces fixed statements from retained field evidence and reproduced screening assessments. Original ranking scores, model inputs and eligibility outcomes remain distinct. See [the operating guide](../docs/reranking-and-explanations.md). Search and screening routes reuse these services.

## Implemented routes

| Route group | Responsibility |
|---|---|
| `health` | Liveness and dependency readiness |
| `search` | Lexical, dense, hybrid, filtered, and reranked trial search |
| `screening` | Patient extraction plus criterion-level verification |
| `trials` | Canonical trial details and parsed criteria |
| `cases` | Inspect the curated synthetic catalog; no narrative creation/upload |
| `experiments` | Run a fixed authored evaluation; inspect saved operations and imported historical reports |

## Service boundaries

- `services/retrieval/`: candidate retrieval, filtering, fusion, and reranking.
- `services/patient_extraction/`: synthetic narrative to auditable facts.
- `services/eligibility/`: deterministic and learned criterion checks.
- `services/explanations/`: evidence-linked output construction.
- `services/embeddings/`: versioned model loading and encoding.
- `repositories/`: persistence interfaces, without domain decision logic.
- `schemas/`: validated API request and response contracts.

`db/models.py`, explicit Alembic migrations and `repositories/postgres.py` implement transactional imports and checksum-validated persistence. Startup never migrates or downloads automatically. `/docs` and `/openapi.json` describe typed search/screening contracts. Real PostgreSQL/Qdrant integration tests complement isolated service and request-validation tests. The API composes the underlying services without changing their research limits.
