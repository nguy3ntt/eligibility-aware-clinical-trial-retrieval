# ADR 0005: Local Qdrant with immutable artifact contracts

- Status: accepted
- Date: 2026-09-05

## Context

Verified bounded exact embeddings exist, but persistence and filter semantics need validation before approximate search or hybrid retrieval. The available diagnostic has 443 judged-pool trials, so it cannot substantiate full-corpus or ANN speed claims. Docker is not installed on the development machine.

## Decision

Use Qdrant 1.19.0 through a small `httpx` REST repository, with pipeline-owned import orchestration and a synthetic-topic CLI. Existing `httpx` suffices; no additional database SDK is required for this bounded surface. Keep the Compose service and offer a checksum-pinned native Windows wrapper for local verification. Both bind to loopback. Native storage uses extended Windows paths and remains Git-ignored.

Use `trials_v1`, one UUIDv5 point per NCT ID, and the planned `overview_dense` named vector with cosine distance. Store immutable artifact/model/template/filter contracts in collection metadata and raw evidence/provenance in each payload. Validate the pinned MiniLM title/condition representation, upload completed batches, and read back every payload/vector. Reject incompatible collections instead of silently overwriting them. Reimporting the identical artifact is idempotent; a future migration should create a versioned collection and explicitly switch an alias only after verification.

Create indexes only for fields currently available: trial ID, artifact digest, sex, and age bounds. Preserve unknowns and raw strings; derive only recognized demographics. Age limits are inclusive within sub-millisecond float tolerance. Derived numeric read-back tolerates serialization noise, while evidence equality is exact. No retrieval output establishes eligibility.

Use exact server search first and compare it with an independent direct-matrix/filter reference. Record actual server configuration. HNSW tuning, ANN recall/latency, snapshots, and restore/rebuild remain a subsequent gate. Keep sparse-vector and criterion-collection additions separate.

## Consequences

The transport can be reused by the later API without importing pipeline orchestration. Saved artifacts remain the source for reproducible loading; Qdrant is never the only copy of records. Full read-back on bounded CLI searches favors integrity over throughput and must be revisited before scaling. Native and Docker storage are distinct. The CLI is single-writer and bounded to the existing dense artifact limit; it does not implement incremental ingestion or model migration.

## Alternatives considered

An embedded imitation would not test the real server. Installing Docker Desktop is unnecessary to verify the same pinned native engine. An SDK would add another versioned dependency without a current need. Unversioned collection reuse risks mixing incompatible vectors. ANN results on an unbuilt small graph could misleadingly look perfect, so approximate-search claims are deferred until graph creation and reference measurements are verified.

## Validation

Offline tests cover invalid inputs, immutable contracts, unfinished writes, and source-preserving payloads. An isolated real-server test checks partial-import recovery, idempotence, exact scores, age/sex boundary behavior, unknowns, and evidence corruption. The saved 443-trial artifact is imported twice, verified after a process restart, and tested on all 50 synthetic topics with and without filters. Code checks and limitations are documented in the operating guide. No full-corpus improvement claim follows from these checks.
