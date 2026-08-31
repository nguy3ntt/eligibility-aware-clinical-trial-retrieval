# Infrastructure

The initial local infrastructure contains one PostgreSQL service and one Qdrant service.

## PostgreSQL

Stores canonical trials, criteria, pipeline state, experiment manifests, and assessments. It becomes active after source inspection and schema design.

## Qdrant

Stores rebuildable dense/sparse retrieval indexes and filterable payloads. It becomes active during the vector-database milestone.

## Commands

```bash
docker compose -f infrastructure/compose.yaml config
docker compose -f infrastructure/compose.yaml up -d
docker compose -f infrastructure/compose.yaml ps
docker compose -f infrastructure/compose.yaml down
```

Named volumes preserve local data between normal container restarts. `docker compose down -v` deletes those volumes and should be used only when intentionally resetting local state.

The default credentials are development-only and must be replaced before any deployment.
