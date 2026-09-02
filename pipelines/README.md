# Pipelines

Pipelines convert public source records into reproducible canonical and indexed data.

## Connectors

Planned functions:

- paginated ClinicalTrials.gov retrieval;
- single-trial lookup;
- retries with bounded backoff;
- immutable raw snapshots;
- TREC topic and qrels loading;
- checkpoints for resumable ingestion.

## Ingestion

Planned functions:

- validate source records;
- normalize trials, conditions, interventions, locations, and age units;
- compute deterministic content hashes;
- perform idempotent upserts;
- record changed, unchanged, malformed, and failed records;
- preserve pipeline manifests.

## Criteria

Planned functions:

- detect inclusion and exclusion sections;
- split atomic clauses;
- classify criterion type;
- detect negation and logical operators;
- parse numeric values and units;
- retain source text, order, and parser version.

## Indexing

Planned functions:

- render versioned trial text;
- generate embeddings in bounded batches;
- create Qdrant collections and payload indexes;
- perform idempotent vector upserts;
- rebuild indexes from canonical data;
- support controlled embedding-model migrations.

No database ingestion, retrieval index, patient extraction, or eligibility decision system is implemented.

## Bounded inspection commands

Run these commands from the project root after installing `pip install -e ".[dev]"` in a Python 3.11+ environment:

```bash
python -m pipelines.inspection fetch --run-id inspection-example --limit 500
python -m pipelines.inspection profile --run-id inspection-example --output-id inspection-example-profile
```

On Windows without activating the environment, replace `python` with `.venv\Scripts\python.exe`.
Acquisition needs internet access; profiling and tests run offline. No API key, database, GPU, or new infrastructure is needed.

`fetch` downloads the official **synthetic** TREC 2022 topics and judgments, then selects unique judged trial IDs by sorting `SHA256(seed + ":" + NCT_ID)` with the NCT ID as a tie-breaker. The default seed is `trec-2022-inspection-v1`; `--seed` records an alternative. The limit is 1–1,000, with 500 intended for this inspection. This is a reproducible sample of **judged trial IDs**, not a representative registry sample or a ranked retrieval result.

The ClinicalTrials.gov fetcher requests explicit ID batches of at most 100. It never scans the corpus or follows a cursor past its requested ID set. A trailing cursor is accepted if every requested ID arrived; an incomplete batch that still advertises pagination fails for inspection. Missing IDs without a cursor are retained as explicit gaps, never silently replaced. Response bodies are capped at 25 MiB, transient HTTP/transport errors get at most three attempts with one- and two-second backoff, and each HTTP operation has a 45-second timeout. This is a bounded inspection connector, not a resumable full ingestion system.

Each run uses a **new** directory under `data/raw/`. Exact decoded HTTP response bodies, retrieval timestamps, request URLs/parameters, SHA-256 checksums, source terms references, code hashes, and API versions are preserved. API metadata is checked before and after acquisition; a change invalidates the run. Existing directories are never reused, even after failure. Failed runs retain a failure manifest and any downloaded bytes; an abrupt process termination can leave sidecars without a final manifest, which profiling refuses.

The 2022 topics file currently has a stale `task="2021 TREC Clinical Trials"` attribute. The loader accepts that exception only for the exact inspected SHA-256 embedded in `connectors/trec.py`, retains the source attribute, and reports a warning. It does not accept arbitrary 2021 topics as 2022. If the mismatched file changes, inspect the official source and update the documented checksum deliberately. The original raw file is never repaired in place.

`profile` verifies checksums before reading source records and writes a new directory under `data/interim/`. To reproduce a saved run offline:

```bash
python -m pipelines.inspection profile --run-id <raw-run-id> --output-id <new-output-id>
```

Use a fresh output ID every time. A new live fetch can differ as source data change; replaying the same saved bytes with the same code is deterministic.

| Output | Purpose |
|---|---|
| `profile.json`, `summary.md` | Field presence counts, source counts, age tokens, phase combinations, and date string lengths |
| `field-inventory.json` | Every observed JSON path, per-record presence, and observed types; array indexes collapse to `[]` |
| `validation-issues.json` | Missing requested IDs and checked field-type failures |
| `topics.jsonl`, `qrels.jsonl` | Validated source rows with synthetic provenance and original identifiers |
| `qrel-trial-trace.jsonl` | Every judgment linked to topic/XML locator, qrel line, and current trial/file/checksum/pointer or an explicit coverage gap |
| `eligibility-examples.json` | Up to six original texts per heading-marker category, with provenance |
| `pair-review.jsonl` | Up to ten distinct trials across judgment grades, preferring distinct topics; review and system assessment remain unset |
| `manifest.json` | Input manifest checksum, configuration, code hashes, and output checksums |

All generated outputs stay local. Publish only reviewed aggregate findings under `docs/experiments/`.

## Interpretation and validation limits

- Missing, null, empty, wrong-type, and present are separate states. `false` and `0` are present values. A malformed parent module is a type error, not silently missing.
- Presence is **not** evidence of usable content: the sample contains the literal placeholder `No eligibility criteria`. Known placeholder strings are flagged without interpreting eligibility.
- The field inventory is observational. The selected-field checks validate outer types; they do not fully validate nested array elements, clinical semantics, date validity, or logical criteria.
- Eligibility heading detection only looks for two literal marker strings. It is not an atomic criterion parser or a measured parser-accuracy result.
- TREC grades 0/1/2 are preserved as source benchmark labels. They are not model predictions or current medical eligibility assessments.
- Current API records can differ from the frozen April 27, 2021 TREC corpus. Every trace says `historical_trial_status="not_loaded"` and `benchmark_comparable=false`. Do not use this sample to claim TREC retrieval metrics.
- Prepared pairs require explicit source review. No automatic eligibility judgment is produced, and no human review is fabricated.

## Tests

`python -m pytest` includes offline pipeline tests as well as the API health check. Tests use tiny invented synthetic records and mocked HTTP; no downloaded topics or trial corpus are required.

## Historical benchmark corpus gate

The TREC Clinical Trials 2021 and 2022 tasks use the same frozen April 27, 2021 ClinicalTrials.gov XML corpus. Acquire the five official archives into a new local snapshot:

```bash
python -m pipelines.historical_corpus fetch --run-id trec-ct-2021-20210427
```

If the process is interrupted, rerun it with `--resume`. Downloads remain under an `.incomplete` staging directory until all five archives match the recorded official byte sizes and `Last-Modified` values. A completed snapshot is immutable and cannot be overwritten.

Validate every archive and XML record offline against the official 2022 qrels:

```bash
python -m pipelines.historical_corpus validate \
  --run-id trec-ct-2021-20210427 \
  --output-id trec-ct-2021-20210427-validation \
  --qrels data/raw/<inspection-run-id>/qrels2022.txt
```

Validation recomputes each archive SHA-256, verifies ZIP member CRCs and safe paths, parses every XML record, checks NCT IDs against filenames, detects duplicates, profiles renderer fields, and confirms that every judged trial ID is present. It writes a local trial-to-archive provenance index under `data/interim/`. No patient assessment or retrieval metric is produced.

The official download page publishes archive names and approximate sizes but no cryptographic hashes. The acquisition therefore pins exact observed byte sizes and server timestamps, records locally computed SHA-256 values, and states this limitation in its manifest. Benchmark scoring remains blocked if any archive, XML record, expected count, or qrel-coverage check fails.

## Retrieval document rendering

Only a completed historical validation may be rendered:

```bash
python -m pipelines.render_trials \
  --run-id trec-ct-2021-20210427 \
  --validation-id trec-ct-2021-20210427-validation-v2 \
  --output-id trec-ct-2021-render-v1
```

The renderer reads the archives without rewriting them and writes one JSON line per trial under `data/processed/`. Each row retains the NCT ID, exact archive/member/CRC provenance, original age/sex metadata, three versioned text representations, and a deterministic content hash. Missing fields add no placeholder text. Output directories are immutable and cannot be reused.

The rendered corpus is an input to retrieval, not a canonical clinical database and not an eligibility decision dataset. All generated documents remain local and Git-ignored.
