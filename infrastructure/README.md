# Infrastructure

The initial local infrastructure contains one PostgreSQL service and one Qdrant service.

## PostgreSQL

Stores canonical trials, criteria, pipeline state, experiment manifests, and assessments. It becomes active after source inspection and schema design.

## Qdrant

Stores rebuildable retrieval indexes and filterable payloads. The implementation loads a verified, bounded MiniLM artifact into `trials_v1`, with an `overview_dense` vector and five payload indexes. Exact/ANN evaluation, explicit graph configuration, snapshots, and isolated recovery/rebuild are available. Sparse vectors remain future work.

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
