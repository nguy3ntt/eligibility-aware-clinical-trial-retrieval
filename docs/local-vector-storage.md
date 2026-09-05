# Local vector storage and exact search

This research workflow uses public historical trials and synthetic TREC topics only. Results are potential matches requiring professional review, never confirmed eligibility. A missing fact does not satisfy a criterion.

## Prerequisites and service

Run commands from the Git repository root with its Python environment active. Install `.[dev,dense]` if needed. Prepare the pinned MiniLM `title_conditions` artifact using the existing dense workflow before loading it. The local diagnostic artifact is `data/processed/dense-m3-minilm-v1` (443 trials, 384 dimensions); data and model weights are intentionally absent from Git. Defaults target this artifact; `--index-id` accepts another verified artifact with the same supported model/template.

Choose one service option. With Docker installed:

```bash
docker compose -f infrastructure/compose.yaml config
docker compose -f infrastructure/compose.yaml up -d qdrant
```

Qdrant is pinned to 1.19.0 and publishes only loopback ports. Its named volume survives ordinary stop/start. The separate PostgreSQL service is not needed for these commands. Never use `down -v` unless deliberately deleting database data.

On Windows without Docker, use PowerShell:

```powershell
.\scripts\qdrant-local.ps1 -Action Start
.\scripts\qdrant-local.ps1 -Action Status
```

First start downloads the [official Windows Qdrant release](https://github.com/qdrant/qdrant/releases/tag/v1.19.0), verifies both archive and executable SHA-256, and keeps it in ignored `artifacts/`. Later starts require no network. If your PowerShell policy blocks scripts, use an appropriately trusted PowerShell session under your normal policy; do not change machine-wide policy for this project. The wrapper uses extended Windows paths to prevent payload-index creation from exceeding the traditional path-length limit. It binds only `127.0.0.1`, disables telemetry, and writes persistent data to ignored `qdrant_storage/`. The executable does not include dashboard static files; use the CLI, not `/dashboard`. Startup warnings about missing optional default config files and unsupported filesystem detection are expected with this native release.

The native and Docker stores are separate. Stop one before starting the other on port 6333. The wrapper owns only its recorded native process; it does not control Docker. Logs and its PID stay in `artifacts/qdrant-1.19.0/`. Native Stop terminates the process, so do not run it during an import. Restart recovery is checked by full read-back; this is not a backup procedure.

## Import and verification

```bash
python -m pipelines.qdrant_index load
python -m pipelines.qdrant_index load
python -m pipelines.qdrant_index verify
```

Each command should report `status: verified`, `points: 443`, `payload_indexes: 5`, and `benchmark_comparable: false` for the saved diagnostic. Two loads keep 443 points rather than doubling them. Import validates source artifacts before writing, uses UUIDv5 derived from NCT IDs, writes batches of 64 with completion acknowledgement, and reads back every ID, vector, and evidence payload. It checks vector values within `1e-6` and derived age serialization within `1e-9` days; source evidence strings must match exactly.

A failed or interrupted import exits unsuccessfully. Retry the same `load` command; unchanged IDs overwrite safely and verification detects missing points. A collection with a different artifact hash, model, template, or schema is rejected, even if the vector dimensions match. Use an explicitly new `--collection` name for a different artifact; commands never delete or silently migrate existing collections. The current workflow is a bounded single-writer workflow, not concurrent incremental ingestion.

The collection stores the model revision, snapshot digest, representation template, source artifact digest, dimension, document count, and filter version in its metadata. Each point retains trial ID, title, raw demographics, derived age/sex fields where known, source archive/member/checksum, and content hash. Qdrant is a rebuildable index, not the authoritative record store. The five payload indexes cover trial ID, artifact digest, sex, minimum age, and maximum age. Status, countries, and other future filters are not invented from missing source fields.

## Manual search

Use an existing official synthetic topic file, not real patient information:

```bash
python -m pipelines.qdrant_index search --topics data/raw/m1-20260831-500-v2/topics2022.xml --topic-id 15 --top-k 5
python -m pipelines.qdrant_index search --topics data/raw/m1-20260831-500-v2/topics2022.xml --topic-id 15 --top-k 5 --filter age_sex
```

Expect `status: complete`, `search_mode: exact`, descending cosine similarities, NCT IDs, source provenance, and `eligibility_assessment: not_performed`. Query encoding uses the same pinned local model snapshot. Search verifies every stored point before returning evidence; this full read-back is appropriate to the bounded diagnostic and will need a different integrity strategy at scale.

Filtering removes only known age/sex contradictions. Unknown/unparseable values remain candidates; `filter_facts` reports the deterministic extractor's age evidence, sex, ambiguity flag, and version. Age limits are inclusive, with a `1e-8` day tolerance (less than one millisecond) for float round trips. Unknown trial sex is retained, including nonstandard strings. The extractor still only examines the synthetic topic's opening 240 characters and is not the planned patient-fact extraction system. Result order can change and fewer results are possible; matching all filters does not establish eligibility. Equal-score results returned by Qdrant are ordered by NCT ID, but selection at the top-k tie boundary is server-dependent.

## Restart and automated checks

```powershell
.\scripts\qdrant-local.ps1 -Action Stop
.\scripts\qdrant-local.ps1 -Action Start
python -m pipelines.qdrant_index verify
```

The point count and verification should be unchanged without reloading. For Docker, use `docker compose -f infrastructure/compose.yaml restart qdrant` instead, then verify when the service is ready.

```powershell
$env:QDRANT_TEST_URL = 'http://127.0.0.1:6333'
python -m pytest evaluation/tests/test_qdrant.py
Remove-Item Env:QDRANT_TEST_URL
python -m evaluation.qdrant_smoke --topics data/raw/m1-20260831-500-v2/topics2022.xml --output-id qdrant-manual-check-01
```

Use a fresh report ID each time. The real-model verifier should report `status: passed` and `exact_checks: 100` for 50 topics. The report stays under ignored `evaluation/reports/` and records hashes, server configuration, point verification, numerical errors, and ID agreement. Without the environment variable, the isolated server integration test is skipped; other Qdrant tests run offline.

If connection fails, start the service. If an artifact/model is missing, prepare it using the existing dense pipeline; the importer does not download it. If a checksum or contract differs, investigate rather than editing the manifest to bypass validation. If a server index operation fails, inspect the native logs; use the wrapper's long-path storage settings on Windows. If verification finds altered evidence or vectors, reload the same immutable artifact and verify again. Extra/unexpected points or an incompatible collection require investigation; no automatic deletion is performed.

## Approximate search and evaluation

Exact search remains the default. To build the bounded HNSW profile and then request ANN search:

```bash
python -m pipelines.qdrant_index configure-ann
python -m pipelines.qdrant_index search --topics data/raw/m1-20260831-500-v2/topics2022.xml --topic-id 15 --top-k 10 --filter age_sex --mode ann --hnsw-ef 128
python -m evaluation.qdrant_ann --topics data/raw/m1-20260831-500-v2/topics2022.xml --output-id ann-manual-01
```

Configuration should report `indexed_vectors: 443`; ANN search should report `search_mode: ann` and `hnsw_ef: 128`. No vector is re-encoded during graph construction. Configuration is idempotent and preserves the artifact contract. It waits up to 120 seconds for complete indexing and fails visibly if the graph is incomplete or the optimizer reports an error. After reloading points, run `configure-ann` again if graph readiness has changed.

The evaluator compares efforts 10, 32, and 128 with exact top-10 neighbors for all supplied synthetic topics, with and without demographics filters. Default repeats are three. It warms both methods, shuffles query/method order with a saved seed, and times only HTTP requests, JSON processing, and result sorting. Each configuration has 150 exact and 150 ANN timed requests for 50 topics. The output includes mean/minimum neighbor recall, median/p95 latency, every ranking and timing sample, configuration/model/code hashes, and telemetry deltas. Recall concerns agreement with exact vector neighbors, not medical eligibility or qrel relevance.

Use a fresh report ID. Do not search, import, configure, restart, or rebuild the measured collection while evaluation runs. The diagnostic requires one populated HNSW segment and exactly one recorded graph search per ANN request; fallback scans or concurrent calls make it fail instead of claiming ANN success. The ordinary search command reports the requested mode; extremely small filtered candidate sets can still cause Qdrant's planner to scan. Only the evaluator verifies the actual search path.

The explicit diagnostic profile uses `m=16`, `ef_construct=100`, one indexing thread, `full_scan_threshold=10` KiB (the pinned server's minimum), `indexing_threshold=1` KiB, and one target optimized segment. These small-corpus settings are not production defaults. See [ADR 0006](architecture/decisions/0006-measured-ann-and-isolated-recovery.md).

## Snapshot, restore, and independent rebuild

Run recovery commands sequentially, with no concurrent writers. Example names below must be new:

```bash
python -m pipelines.qdrant_index snapshot --backup-id manual-backup-01
python -m pipelines.qdrant_index restore --backup-id manual-backup-01 --collection manual_restored_01 --report-id manual-restored-01
python -m pipelines.qdrant_index rebuild --collection manual_rebuilt_01 --report-id manual-rebuilt-01
python -m pipelines.qdrant_index verify --collection manual_restored_01
python -m pipelines.qdrant_index verify --collection manual_rebuilt_01
```

Snapshot should report `status: complete`; restore/rebuild should report `status: verified` and `indexed_vectors: 443`. The source `trials_v1` remains unchanged. Both target collections reject later attempts to overwrite them, even when empty or holding the same artifact. There is no destructive reset flag or automatic collection switch. If a failed operation leaves a partial target, inspect it and use a new target name; do not delete the working collection to retry.

Snapshots and their manifests live in ignored `artifacts/qdrant-backups/<backup-id>/`. Restore verifies the snapshot checksum, size, server version, and artifact/model contract before upload; it then compares every recovered vector, evidence payload, index, and collection configuration. A source artifact is required even for restore so recovered evidence can be independently verified. Use only trusted project-generated backups: checksums do not authenticate a maliciously replaced manifest. Downloads are capped at 512 MiB for this bounded workflow.

The server retains its own snapshot as well as the downloaded copy. In the measured run each was about 173 MiB despite less than 1 MiB of raw vectors, because snapshots contain engine storage files. Allow at least 1 GiB free for a manual backup/recovery exercise. No automated snapshot retention/deletion or off-device backup is provided; copies on one disk are not disaster protection.

Rebuild reads the immutable dense artifact directly and does not use the snapshot or source collection. To recreate that artifact from the saved historical/rendered data, use the earlier `render_trials` pipeline, `evaluation.run_dense_diagnostic prepare` to reproduce the judged pool, then `pipelines.dense encode --representation title_conditions --model minilm` with fresh output IDs. Manifest hashes for freshly generated artifacts differ because generation metadata is recorded; use a new collection for the new artifact, never edit a manifest to make it match an old collection. Graph bytes need not be deterministic; exact-vector correctness and measured ANN recall are the reproducibility checks.

For a complete read-only recovery check, including source-text re-encoding in batches of 16:

```bash
python -m evaluation.qdrant_recovery_smoke --topics data/raw/m1-20260831-500-v2/topics2022.xml --collections trials_v1 manual_restored_01 manual_rebuilt_01 --output-id manual-recovery-check-01
python -m evaluation.qdrant_ann --topics data/raw/m1-20260831-500-v2/topics2022.xml --collection manual_rebuilt_01 --output-id manual-rebuilt-ann-01
```

The recovery check should report `status: passed`, `documents_reencoded: 443`, and 100 exact-search checks for each collection. It compares every payload/vector and verifies the restored/rebuilt graphs. Repeat after restarting the server using the earlier procedure. The standalone ANN test is separate because graph rebuilding can change approximate neighbors.

Run the offline and opt-in server regression tests:

```powershell
python -m pytest evaluation/tests/test_qdrant.py evaluation/tests/test_qdrant_ann.py
$env:QDRANT_TEST_URL = 'http://127.0.0.1:6333'
python -m pytest evaluation/tests/test_qdrant.py evaluation/tests/test_qdrant_ann.py
Remove-Item Env:QDRANT_TEST_URL
```

Without the variable, two server tests skip; the other tests require no service or downloaded model. Live tests create and delete only randomly named test collections. The current project workflow is single-writer; it does not implement transactional concurrency or active-collection alias migration.

## Scope and remaining work

The existing 443-trial pool was selected using judgments. It supports bounded correctness, ANN neighbor-recall, latency, and recovery measurements, but does not establish full-corpus retrieval quality or performance. The earlier full-corpus dense comparison remains deferred.

ANN, snapshot/restore, and artifact-only rebuilding are implemented and tested within this bounded scope. Larger-scale validation, hybrid sparse fusion, and application search endpoints remain separate work. No new API/UI, automatic eligibility decisions, cloud service, or real patient ingestion is introduced here. The measured small collection does not demonstrate a meaningful ANN speed advantage; exact search remains the default.
