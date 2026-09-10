# ADR 0012: Local research API and immutable PostgreSQL evidence

Date: 2026-09-10. Status: accepted for bounded local research.

## Context

The existing services are tested through commands but need stable HTTP contracts and persistent source/results storage. The retrieval and screening promotion gates remain unmet. API integration must not broaden patient input or turn relevance into eligibility.

## Decision

Expose versioned `/v1` search, screening, case/trial lookup and experiment routes through FastAPI. Only identifiers from an explicitly seeded synthetic/public catalog are accepted. No narrative upload, arbitrary file path, remote URL, unrestricted job execution, account system or generative chatbot is added. `/health` stays independent of infrastructure. `/v1/ready` checks the migrated PostgreSQL catalog and Qdrant contract; models load lazily for operations that need them.

Use the already planned PostgreSQL, SQLAlchemy and Alembic stack. Explicit operator commands migrate and transactionally seed immutable catalogs, case records and full trial evidence. Composite catalog/record identifiers and SHA-256 payload hashes prevent accidental overwrites. Full field/criterion evidence stays in JSONB under relational keys and foreign keys; preserve existing schema versions rather than flattening away uncertainty. A completed operation is written atomically only after successful verification. API startup does not migrate, import, download or alter vector collections.

The initial catalog contains 50 official synthetic TREC cases and one invented demonstration case; 443 historical trial records and three invented demonstrations. All historical field evidence must reproduce the prior retrieval artifact. Optional CLI import stores a completed local experiment manifest with its exact source checksum and an explicit historical label. HTTP experiment execution permits only the existing bounded authored screening evaluation; long-running retrieval diagnostics remain explicit CLI jobs.

Use exact dense plus legacy age/sex by default. Sparse, hybrid, profile filtering, reranking and NLI advisories require explicit options. Qdrant results retain branch scores/evidence; fresh searches verify all vectors and payloads in the bounded collection. PostgreSQL trial evidence must match the catalog and artifact before explanation. Full-clause screening and fixed explanations are reused unchanged. Optional NLI suggestions never affect outcomes or ranking.

An operation identity hashes request options, catalog/source identity, executable-code fingerprints and runtime versions. Duplicate identical requests return the persisted packet with `replayed: true`, explicitly denoting historical replay rather than fresh inference. Source/code changes produce different identities. A single-worker nonblocking gate serializes expensive operations; overlapping work returns 429, with no hidden job queue or distributed infrastructure. Read-only lookups remain available. Stored research results are not current trial eligibility decisions.

Bind the supported launcher to loopback, reject nonlocal Host/Origin values, cap bodies at 16 KiB and bound result counts. Disable access logs in the launcher. Validation and dependency failures use fixed error envelopes without input values, SQL parameters, credentials or paths. Consume unexpected application exceptions before server middleware can re-raise them into logs. No clinical text is uploaded to model providers. This boundary is for local research, not authentication or an internet deployment security review.

Reuse installed PostgreSQL binaries for an optional project-owned cluster on port 55432, storing data/logs in ignored artifacts and random credentials in ignored `.env.api.local`. Do not alter installed PostgreSQL services or other databases. Compose PostgreSQL binds only to loopback; native and Docker stores remain separate. Migration rollback testing uses newly created isolated test schemas only.

## Consequences

The API remains bounded and synchronous, exposes Swagger/OpenAPI for manual use, and preserves all earlier limitations. Cached results may remain readable when a dependency is unavailable; the replay flag makes this explicit. PostgreSQL/real-Qdrant, source tampering, restart persistence, idempotency, error privacy and model paths require integration checks. Models and raw/generated data stay local; no Git commit/push is performed. React UI, broad clinical validation, full-corpus scaling and deployment remain outside this milestone.
