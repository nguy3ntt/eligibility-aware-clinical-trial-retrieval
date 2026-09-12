# Reproducing the research release

This release separates a full **375,580-trial offline retrieval experiment** from the
**443-trial local interactive diagnostic**. The application catalog also contains three
invented trials and 51 synthetic cases. The full corpus is not silently substituted into
the app. Current registry updates are a third, isolated lineage. None determines medical
eligibility or earns model promotion.

Read the [experiment report](experiments/0011-full-corpus-release-and-hardening.md) for
results and limitations, and [ADR 0015](architecture/decisions/0015-reproducible-local-research-release.md)
for the boundaries. All commands below run from the repository root. Output IDs must be new.

## Environment and source identity

The observed research runtime is Windows 11, Python 3.12.14, four CPU threads, float32 and
Node 24.16.0/npm 11.13.0. No GPU or paid inference API is required. Use a short virtual
environment path on Windows: deeply nested Torch installation paths can exceed Windows'
filename limit. The local Windows launchers expect Python at `../.venv/Scripts/python.exe`;
generic Python entry points can use any activated environment.

```powershell
python -m venv ../.venv
../.venv/Scripts/Activate.ps1
python -m pip install -r requirements/research.txt
python -m pip check
```

The dependency constraints record observed versions, not a universal wheel lock.
Linux CI checks engineering behavior; it does not establish identical model arithmetic
across operating systems. A saved dense index rejects a different query runtime. Build a
new index when migrating the runtime instead of weakening this check.

Allow at least 16 GB RAM (32 GB recommended) and approximately 15 GB free disk for a fresh
corpus, render, models, dependencies and generated evidence; additional rebuilds require
additional space. The observed full index took 80.7 minutes on this CPU, including workload
contention. Its normalized vector matrix alone occupies about 577 MB. The rendered JSONL
is 2.46 GB. These are planning measurements, not hardware guarantees.

For a reviewable copy of all publishable working files, including uncommitted changes:

```powershell
python -m evaluation.release_source --output artifacts/release-source-review
```

This read-only Git operation copies source and writes a sorted SHA256 inventory, base
commit and dirty-worktree flag. It refuses ignored tracked files, missing files and unsafe
paths. It never stages, commits or pushes. The inventory identifies actual file bytes;
the base commit alone does not identify uncommitted work. The export is local and ignored.
Review and commit source manually, then record the resulting commit/tag when publishing.
Checksums detect changes, but do not authenticate an external publisher.

## Full frozen benchmark

Acquire official synthetic topics/qrels using the [pipeline guide](../pipelines/README.md).
The observed snapshot ID is `m1-20260831-500-v2`; substitute your own path in the options.
Acquire, validate and render the historical corpus using that guide before encoding:

```powershell
python -m pipelines.historical_corpus fetch --run-id trec-ct-2021-20210427
python -m pipelines.historical_corpus validate --run-id trec-ct-2021-20210427 --output-id trec-validation-release --qrels data/raw/m1-20260831-500-v2/qrels2022.txt
python -m pipelines.render_trials --run-id trec-ct-2021-20210427 --validation-id trec-validation-release --output-id trec-ct-2021-render-v1
python -m pipelines.dense prepare-model --model minilm
python -m pipelines.prepare_reranker
python -m pipelines.release_index build --output data/processed/release-full-minilm-v2
python -m pipelines.release_index verify --output data/processed/release-full-minilm-v2
python -m evaluation.release_benchmark --output evaluation/reports/release-full-reproduction
```

Only acquisition/model preparation uses the network. A stopped index build can resume
with the same command plus `--resume`; every completed shard is checked and reused.
Source, code, model and configuration must remain identical. Incomplete attempts remain
separate and cannot be searched. A completed benchmark output is never overwritten.

The benchmark requires all 375,580 frozen records, the exact official 50 topics/qrels,
and matching document/query encoder identities. It writes the protocol before metrics,
builds matched title/condition BM25, compares full exact dense dot products with a blocked
reference, and evaluates six retrieval/filter configurations plus reranking depths 10/20.
RRF uses equal branches, rank constant 60 and branch depth 100. Stable NCT IDs break ties.
Reranking adds summary text, so it is not a controlled model-only comparison.

Outputs include eight TREC runs, full rank/branch evidence, per-topic metrics, exploratory
paired bootstrap intervals, component timings, model/input identities and 150 original-XML
explanations. Reranked run scores are rank surrogates so score-sorting readers preserve
prefix/tail order. Raw cosine, BM25, RRF and learned scores remain separate in JSON.
MRR is truncated at 100; grade-1/2 recall concerns historical qrel labels, not current
screening decisions. Never select parameters on these previously inspected topics and
then call them held out.

## Incremental current-registry updates

```powershell
python -m pipelines.incremental fetch --snapshot-id registry-example-01 --start 2000-01-01 --until 2026-09-11 --ids NCT01726751,NCT03325374,NCT02749071 --page-size 1 --max-pages 10
python -m pipelines.incremental verify --snapshot-id registry-example-01
python -m pipelines.incremental apply --snapshot-id registry-example-01 --output-id registry-example-01
```

Use an explicit date window ending no later than today. Omit `--ids` only for an intentional
bounded all-registry window. For subsequent windows use the previous manifest's
`next_start_with_overlap`, a new end date/snapshot ID and `apply --previous-id <previous>`.
Dates overlap to capture same-day updates. Stable NCT IDs and canonical record hashes
distinguish added, changed and unchanged records. Absence never implies deletion.

Raw responses and source metadata are immutable. Checkpoint resume requires the same
query and unchanged API data timestamp. Malformed/duplicate records, broken cursors,
revision changes, exhausted page budgets and regressing record dates prevent completion
or watermark advancement. Failures retain evidence; narrow the window into a new snapshot
when the page budget is insufficient. Verification is integrity checking, not protection
against a maliciously rewritten entire artifact. The API timestamp is a consistency guard,
not a server-side transactional snapshot guarantee. Updates never alter the frozen TREC
corpus, active application catalog or vectors automatically.

## Migration and recovery

1. Freeze the old catalog/index/model manifests and make a verified Qdrant snapshot.
   Retain immutable PostgreSQL operation evidence and a database backup using normal
   PostgreSQL tooling before changing its storage or schema. Keep credentials local.
2. Prepare the new pinned model in a separate snapshot. Changes to revision, dimension,
   pooling, token limit, prompt, representation, normalization or runtime require new
   document **and** query embeddings. Never mix vector spaces or overwrite the old index.
3. Build into a new artifact/collection name. The full release builder intentionally supports
   only its fixed MiniLM protocol; a different model requires a reviewed versioned protocol.
   The bounded dense pipeline supports the separately pinned PubMedBERT diagnostic.
4. Check hashes, counts, payload/source equality, document re-encoding and exact neighbors.
   Configure the graph and compare ANN against exact results on identical filters/vectors.
   Re-evaluate relevance and screening evidence independently. A technically valid rebuild
   is not evidence of better retrieval or clinical accuracy.
5. Only explicitly switch application configuration after those checks and review. Retain
   old artifacts/configuration for rollback; do not infer promotion from this release.

The implemented Qdrant recovery commands are:

```powershell
python -m pipelines.qdrant_index snapshot --backup-id recovery-example
python -m pipelines.qdrant_index restore --backup-id recovery-example --collection restored_example --report-id restored-example
python -m pipelines.qdrant_index rebuild --collection rebuilt_example --report-id rebuilt-example
python -m evaluation.qdrant_recovery_smoke --topics data/raw/m1-20260831-500-v2/topics2022.xml --collections trials_v1 restored_example rebuilt_example --output-id recovery-example
python -m evaluation.qdrant_ann --topics data/raw/m1-20260831-500-v2/topics2022.xml --collection rebuilt_example --output-id ann-example
```

See [vector operations](local-vector-storage.md) for prerequisites and
[API operations](local-research-api.md) for explicit migrations/catalog import. Do not modify
the installed Windows PostgreSQL service. The project uses its own loopback 55432 cluster.
Readiness becomes unavailable when dependencies stop; saved evidence is historical, not
fresh inference. Restarting a service must preserve operation IDs, evidence and vector counts.
Launchers refuse to stop a foreign/recycled PID; Start checks the port before replacing a stale
PID record. No unattended destructive recovery or storage deletion is performed.

## Engineering checks and demo

```powershell
ruff check .
ruff format --check .
pytest
python -m compileall backend pipelines evaluation
```

`requirements/ci.txt` is the lighter environment for public fixture tests. Real PostgreSQL,
Qdrant and model tests require explicit flags and prepared dependencies, documented in their
operating guides. CI runs backend lint/format/tests with isolated PostgreSQL/Qdrant services,
and frontend locked install/format/unit/build/offline Chrome tests. Actions are pinned by
commit with read-only repository permissions. Large models/corpus and actual-service UI
tests are deliberately excluded from hosted CI. A hosted green run can only be established
after a manual push; local verification does not claim that run happened.

Start the existing local services and follow [the browser guide](research-workspace.md).
To reproduce the five-scene portfolio recording from `frontend/`:

```powershell
npm ci
npx playwright install chrome ffmpeg
$env:RUN_RELEASE_DEMO='1'
npx playwright test e2e/release-demo.spec.ts
```

It records search, original source, unknown screening with NOT PROMOTED NLI, retrieval
comparison and the authored experiment dashboard. Video/screenshots are under ignored
`frontend/test-results/`; preserve them locally before another browser run replaces them.
Run the recording alone, without concurrent HTTP/load checks: the one-worker app
intentionally rejects a second active operation with a retryable busy response.
Use only these verified synthetic/public scenes for a portfolio. Reviewed code/docs belong
in Git; raw data, models, credentials, recordings, reports and private planning stay ignored.
This release includes no cloud deployment, authentication or production security claim.
