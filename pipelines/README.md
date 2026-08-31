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

## Milestone 1 inspection commands

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

`profile` verifies checksums before reading source records and writes a new directory under `data/interim/`. To reproduce the recorded run offline:

```bash
python -m pipelines.inspection profile --run-id m1-20260831-500-v2 --output-id inspection-replay
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

All generated outputs stay local. Commit reviewed aggregate findings under `docs/experiments/`, not these files.

## Interpretation and validation limits

- Missing, null, empty, wrong-type, and present are separate states. `false` and `0` are present values. A malformed parent module is a type error, not silently missing.
- Presence is **not** evidence of usable content: the sample contains the literal placeholder `No eligibility criteria`. Known placeholder strings are flagged without interpreting eligibility.
- The field inventory is observational. The selected-field checks validate outer types; they do not fully validate nested array elements, clinical semantics, date validity, or logical criteria.
- Eligibility heading detection only looks for two literal marker strings. It is not an atomic criterion parser or a measured parser-accuracy result.
- TREC grades 0/1/2 are preserved as source benchmark labels. They are not model predictions or current medical eligibility assessments.
- Current API records can differ from the frozen April 27, 2021 TREC corpus. Every trace says `historical_trial_status="not_loaded"` and `benchmark_comparable=false`. Do not use this sample to claim TREC retrieval metrics.
- The ten prepared pairs require human review. No automatic eligibility judgment is produced, and no human review is fabricated.

## Tests

`python -m pytest` includes offline pipeline tests as well as the API health check. Tests use tiny invented synthetic records and mocked HTTP; no downloaded topics or trial corpus are required.
