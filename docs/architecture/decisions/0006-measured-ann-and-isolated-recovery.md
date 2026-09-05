# ADR 0006: Measured ANN and isolated recovery

- Status: accepted
- Date: 2026-09-05

## Context

The local 443-trial collection was below Qdrant's default indexing thresholds. Merely sending `exact=false` would not demonstrate HNSW retrieval. Persistence checks also do not establish snapshot recovery or independence from the running database. The judged pool remains a bounded diagnostic, not a full-corpus benchmark.

## Decision

Keep exact search as the CLI default. Offer explicit ANN requests with `hnsw_ef` in 10..512 (default 32). Configure a named bounded diagnostic profile: `m=16`, `ef_construct=100`, `max_indexing_threads=1`, `full_scan_threshold=10` KiB, `indexing_threshold=1` KiB, and one target optimized segment. Qdrant 1.19.0 rejects a scan threshold below 10; do not use zero. These are experimental settings for this small corpus, not production tuning recommendations.

Require the matching artifact contract, complete point count, green/healthy collection, and every vector indexed before ANN use. The evaluation also requires one populated HNSW segment and checks collection-specific level-4 telemetry before/after each measurement window. The segment identity must remain stable, and `filtered_large_cardinality` and `filtered_exact` must each increase by exactly the paired query count, with no other search increments. Every query includes the artifact filter, so even the `none` demographic configuration uses the filtered HNSW code path. Reject scans, restarts, rebuilds, or competing queries instead of publishing misleading ANN results.

Compare efforts 10, 32, and 128 over the same 50 synthetic topics, with and without demographics filtering. Check exact server scores against a direct matrix reference first. Record strict neighbor-ID Recall@10, available-reference denominator, per-query ranks, individual latency samples, median/p95 latency, warmup, seeded paired-order randomization, versions, hashes, query truncation, environment, and actual configuration. Time warm sequential HTTP/JSON/result sorting only; encoding, integrity validation, and telemetry are outside the interval. No significance or full-corpus speed claim follows from these timings.

Snapshots use the official collection snapshot/download and upload-recovery endpoints. Verify all evidence before/after backup, require SHA-256 and byte-count agreement, cap downloads at 512 MiB, and preserve a manifest beside the downloaded file. Restore only a complete matching backup into an absent target collection. Rebuild only from a verified saved dense artifact into an absent target. Neither workflow deletes, replaces, or switches the active collection. Both verify every vector/payload and HNSW readiness. Use separate immutable progress/final files; failures remain inspectable and fresh IDs are required on retry.

The workflow is single-writer. The absence check is not an atomic concurrency lock; do not run competing recovery/import commands. Checksums detect accidental corruption, not malicious replacement of both snapshot and manifest. Use only trusted project-generated local backups. The repository does not extract arbitrary archives or ask the server to fetch external snapshot URLs.

## Consequences

The later hybrid/API work can reuse the same repository, collection contract, evidence payloads, and recovery boundary. Sparse scores must still be fused by a defined method; this change does not introduce eligibility decisions. ANN requests may lose neighbors, so exact search remains available. A newly rebuilt graph can differ even with identical vectors; reevaluate its recall rather than requiring byte-identical graph files.

Snapshots include engine files and can be much larger than raw vectors (about 173 MiB in this diagnostic). Keep both server and downloaded copies local and budget storage accordingly. Backups on the same disk are recovery demonstrations, not disaster protection. Future scale work should revisit thresholds, integrity-check cost, concurrent ingestion, retention, migration/alias switching, and off-device backup policy.

## Validation

Run offline metric, invalid-input, unbuilt-index, telemetry-fallback, corrupt/truncated-backup, immutable-report, and existing-target protection tests. The opt-in server test uses invented documents/vectors and disposable uniquely named collections. On the real artifact, verify snapshot restore and independent rebuild, restart the server, compare 100 exact searches per collection, and re-encode all 443 source representations in batches of 16. Save a separate ANN evaluation after rebuilding.

## References

- [Collection configuration API](https://api.qdrant.tech/api-reference/collections/update-collection)
- [Snapshot creation API](https://api.qdrant.tech/api-reference/snapshots/create-snapshot)
- [Uploaded snapshot recovery API](https://api.qdrant.tech/api-reference/snapshots/recover-from-uploaded-snapshot)
- [Pinned telemetry implementation](https://github.com/qdrant/qdrant/blob/v1.19.0/lib/collection/src/shards/local_shard/telemetry.rs)
