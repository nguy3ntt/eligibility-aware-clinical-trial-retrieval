# ADR 0001: Separate the source of truth from the retrieval index

- Status: accepted
- Date: 2026-08-31
- Owners: project maintainers

## Context

Clinical-trial records, ingestion state, experiment configurations, and criterion assessments require relational integrity and durable versioning. Vector retrieval requires specialized dense/sparse indexes and filterable payloads.

## Decision

Use PostgreSQL as the authoritative structured store and Qdrant as a rebuildable retrieval index. Preserve raw source snapshots outside both systems.

## Consequences

- Qdrant collections can be rebuilt or migrated without losing canonical data.
- Relational reporting and ingestion state remain straightforward.
- The system has two persistence components and must keep stable IDs synchronized.
- Integration tests must verify PostgreSQL–Qdrant consistency.

## Alternatives considered

- Qdrant only: simpler initially, but unsuitable as the sole canonical experiment and ingestion store.
- PostgreSQL with pgvector only: credible and worth a later comparison, but provides less direct exposure to a dedicated multi-representation vector database.

## Validation

Milestone 4 must demonstrate that Qdrant can be deleted and reproduced from canonical data plus a versioned embedding configuration.
