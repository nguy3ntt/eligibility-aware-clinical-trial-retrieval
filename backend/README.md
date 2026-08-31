# Backend

The backend will expose stable application contracts and orchestrate services. It must not contain source-specific ingestion logic or notebook-derived hidden state.

## Planned routes

| Route group | Responsibility |
|---|---|
| `health` | Liveness and dependency readiness |
| `search` | Lexical, dense, hybrid, filtered, and reranked trial search |
| `screening` | Patient extraction plus criterion-level verification |
| `trials` | Canonical trial details and parsed criteria |
| `patient_cases` | Synthetic case creation and inspection |
| `evaluations` | Start, inspect, and compare experiments |

## Service boundaries

- `services/retrieval/`: candidate retrieval, filtering, fusion, and reranking.
- `services/patient_extraction/`: synthetic narrative to auditable facts.
- `services/eligibility/`: deterministic and learned criterion checks.
- `services/explanations/`: evidence-linked output construction.
- `services/embeddings/`: versioned model loading and encoding.
- `repositories/`: persistence interfaces, without domain decision logic.
- `schemas/`: validated API request and response contracts.

Only a minimal health endpoint is implemented in the initial scaffold.
