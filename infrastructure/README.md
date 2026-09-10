# Infrastructure

The initial local infrastructure contains one PostgreSQL service and one Qdrant service.

## PostgreSQL

Stores the active immutable catalog, verified synthetic cases and trial source records, and completed API operations with full assessments/provenance. Explicit Alembic migrations own four bounded tables; broader normalized entities remain a future design. Both Compose and the optional native Windows setup bind only to loopback. See [API persistence and startup](../docs/local-research-api.md).

## Qdrant

Stores rebuildable retrieval indexes and filterable payloads. The verified MiniLM artifact in `trials_v1` remains intact. `trials_hybrid_v1` adds named dense/sparse vectors and `criteria_v1` holds the bounded criterion diagnostic. Exact/ANN evaluation, explicit graph configuration, snapshots, and isolated recovery/rebuild are available. The API uses the existing hybrid collection even for its default exact dense branch; no new index is required.

See [local vector storage](../docs/local-vector-storage.md) for installation, imports, exact search, verification, and troubleshooting. Docker and native Windows use separate persistent stores; choose one at a time.

## Commands

```bash
docker compose -f infrastructure/compose.yaml config
docker compose -f infrastructure/compose.yaml up -d
docker compose -f infrastructure/compose.yaml ps
docker compose -f infrastructure/compose.yaml down
```

Named volumes preserve local data between normal container restarts. `docker compose down -v` deletes those volumes and should be used only when intentionally resetting local state.

The default credentials are development-only and must be replaced before any deployment.
