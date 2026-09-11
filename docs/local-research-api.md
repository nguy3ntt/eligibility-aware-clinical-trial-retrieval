# Local research API

The API connects verified synthetic cases, public/invented trial evidence, Qdrant retrieval and PostgreSQL persistence. It is a bounded local research application, not a medical eligibility service. No React interface, authentication, cloud deployment or arbitrary patient-text input is added.

## Current catalog and behavior

The prepared catalog contains 51 synthetic cases (50 official TREC 2022 cases plus `reranking-demo`) and 446 trials (443 historical records plus three invented demonstrations). Case and trial endpoints inspect these versioned records; they do not accept arbitrary creation/editing of patient narratives. Add future source versions through explicit, validated ingestion work rather than posting text to this API.

Search defaults remain exact dense retrieval, legacy age/sex filters and no reranking. Sparse, hybrid, profile filtering and reranking are explicit request options. Search returns full evidence explanations and deterministic screening for the displayed results; relevance scores never imply eligibility. An optional screening-only NLI advisory stays non-promoted. Historical trial wording frequently produces `insufficient_information`; broader screening and ranking-promotion gates remain unmet.

PostgreSQL stores immutable catalog identities, source records and completed operations with checksums. Original trial fields and full criterion evidence are retained. Repeating a request with the same options, sources, code and runtime returns the same operation ID with `replayed: true`. That means a saved result, not a fresh assessment or new search. Changes to source/code/runtime identity create a new operation. Failed operations do not create a completed result.

## Start in this Windows workspace

Run from the nested Git repository. The models, artifacts, database dependencies, migrations and initial catalog have already been prepared here.

```powershell
cd E:\eligibility-aware-clinical-trial-retrieval\eligibility-aware-clinical-trial-retrieval
.\scripts\postgres-local.ps1 -Action Start
.\scripts\qdrant-local.ps1 -Action Start
.\scripts\api-local.ps1 -Action Start
```

Open [the interactive API documentation](http://127.0.0.1:8000/docs). Each endpoint has a **Try it out** button. Use the request bodies below and inspect the response. Swagger may need internet access to load its browser assets; PowerShell tests work without it.

The native PostgreSQL wrapper reuses installed PostgreSQL 17 binaries for a separate project-owned cluster on loopback port 55432. It never alters the installed Windows PostgreSQL service or its databases. Data/logs live under ignored `artifacts/postgres-local/`; generated random credentials stay in ignored `.env.api.local`. The API uses that local environment after `.env`, with explicit environment variables taking precedence. Never publish either credentials or database files. PostgreSQL 17.6 was present on this machine; this work does not upgrade it or establish suitability for deployment.

To stop only these project services, use their wrappers with `-Action Stop`. Normal stops preserve saved data. The API launcher uses port 8000, one worker, loopback binding and disabled access logs. Model loading happens on the first operation that needs each model. An overlapping expensive operation returns 429; retry after the running operation finishes.

## Fresh environment preparation

Install the existing extras with `pip install -e ".[dev,database,hybrid,verification]"`. Follow earlier guides to prepare the dense/hybrid artifacts, Qdrant collection, reranking field evidence and optional model weights. Choose native PostgreSQL or Docker; their stores and ports are separate. Docker users configure their local `DATABASE_URL` and use `docker compose -f infrastructure/compose.yaml up -d postgres`; the Compose port binds only to loopback.

Explicitly migrate and import before using the API:

```powershell
..\.venv\Scripts\python.exe -m pipelines.api_data migrate
..\.venv\Scripts\python.exe -m pipelines.api_data seed
..\.venv\Scripts\python.exe -m pipelines.api_data status
```

Migration and identical re-import are repeatable. Conflicting immutable records fail and the import transaction rolls back; do not overwrite a source version to make it fit. API startup never migrates, downloads models, seeds records or changes vector collections automatically.

## Endpoint contracts

| Method and path | Purpose |
|---|---|
| `GET /health` | Liveness without database/model requirements |
| `GET /v1/ready` | Check PostgreSQL revision/catalog and Qdrant contract; model files load lazily |
| `GET /v1/cases` | Paginated synthetic catalog IDs |
| `GET /v1/cases/{case_id}` | Synthetic source and extracted evidence-backed profile |
| `GET /v1/trials` | Paginated trial IDs, titles and source kinds |
| `GET /v1/trials/{trial_id}` | Original field evidence and full conservative criterion parse |
| `POST /v1/search` | Retrieve, optionally rerank, explain and persist a bounded result |
| `POST /v1/screening` | Screen a catalog case/trial pair; optional non-promoted NLI |
| `GET /v1/experiments` | Paginated saved API runs and imported experiment manifests |
| `GET /v1/experiments/{operation_id}` | Read the full saved operation or historical experiment |
| `POST /v1/experiments` | Run only the fixed authored screening evaluation |

List limits are 1–50 and offsets 0–10,000. Search `top_k` is 1–10 and `rerank_depth` 1–50. Extra fields, malformed IDs and coerced booleans/numeric values are rejected. Bodies are capped at 16 KiB, including chunked requests. Remote Host/Origin values are rejected. No arbitrary report paths, remote URLs, patient text or generic background-job requests are accepted.

Errors use `{"error":{"code":"...","message":"..."}}` without echoing submitted input, credentials, SQL parameters or paths. Typical statuses: 404 unknown record, 409 evidence/version conflict, 413 oversized body, 422 invalid request, 429 busy, 503 missing/unavailable dependency. Liveness remains 200 during database outages. PostgreSQL is required to read saved results; when only Qdrant is unavailable, a stored replay can still return 200 with `replayed: true`, while fresh search and readiness fail with 503.

## Manual tests

In PowerShell:

```powershell
$base = 'http://127.0.0.1:8000'
Invoke-RestMethod "$base/health"
Invoke-RestMethod "$base/v1/ready"
Invoke-RestMethod "$base/v1/cases?limit=3"
```

Expect `ok`, `ready`, and a catalog total of 51.

Test an invented pair:

```powershell
$body = @{case_id='reranking-demo'; trial_id='NCT90009002'} | ConvertTo-Json
$screen = Invoke-RestMethod "$base/v1/screening" -Method Post -ContentType 'application/json' -Body $body
$screen.result.assessment.status
$screen.result.explanation.criteria | Select-Object outcome, statement
```

Expect `potential_match` with supported age, sex and hemoglobin rules. Repeat with `NCT90009001` for missing creatinine evidence and `insufficient_information`; use `NCT90009003` for an age blocker and `likely_exclusion`. These are invented research examples, not clinical eligibility decisions.

Test default search:

```powershell
$body = @{case_id='trec-ct-2022:29'} | ConvertTo-Json
$search = Invoke-RestMethod "$base/v1/search" -Method Post -ContentType 'application/json' -Body $body
$search.result.results | Select-Object trial_id, @{Name='screening_status'; Expression={$_.screening.status}}
$search.result.method
$search.result.fact_extractor
```

Expect `dense`, `legacy`, age/sex filtering, no reranker, and these first three IDs: `NCT01726751`, `NCT03325374`, `NCT02749071`. All three screening summaries remain insufficient information. Inspect `result.results[0].relevance.fields`, `.relevance.ranking` and `.screening.criteria` for evidence and separate meanings.

Repeat the exact search: its `operation_id` should match and `replayed` should be true. Retrieve its persisted result:

```powershell
Invoke-RestMethod "$base/v1/experiments/$($search.operation_id)"
```

Restart the API with its Stop/Start wrapper and retrieve that ID again. Results remain stored in PostgreSQL. Use `method='sparse'` or `'hybrid'`, `fact_extractor='profile'`, or `rerank=$true` explicitly to test optional search paths. To inspect learned screening advisories, add `semantic=$true` to the `NCT90009001` screening request: `promoted` remains false and status remains insufficient information.

Run the bounded evaluation through HTTP:

```powershell
$experiment = Invoke-RestMethod "$base/v1/experiments" -Method Post -ContentType 'application/json' -Body '{}'
$experiment.result.status
$experiment.result.evaluation.exact_pairs
$experiment.result.evaluation.criterion_count
```

Expect `passed`, 34 exact invented pairs and 41 criteria. This is authored development evaluation, not independent clinical validation. A completed prior experiment can also be imported explicitly with `python -m pipelines.api_data import-experiment --report-id m9-reranking-release`; it is labelled historical and does not rerun or promote that model.

For a failure sanity check in Swagger, set search `top_k` to 11 or add a `text` field containing only an invented placeholder. Expect 422 with a fixed error envelope and no echoed value. Never submit real patient information, even when testing rejection.

## Automated HTTP checklist

```powershell
..\.venv\Scripts\python.exe -m evaluation.api_smoke --output-id my-api-check-01
```

Expect `status: passed` and 24 checks over the running services. This includes all retrieval modes, optional models, saved operations, invented screening outcomes and invalid requests. Use a new output ID for each run; existing reports are protected.

For the complete local integration suite, set `RUN_POSTGRES_TESTS=1`, `RUN_API_INTEGRATION=1`, `RUN_NLI_TESTS=1`, `RUN_RERANKER_TESTS=1` and `QDRANT_TEST_URL=http://127.0.0.1:6333` before running pytest. PostgreSQL tests create/drop only uniquely named test schemas and use actual Alembic migrations; there is no production SQLite fallback. See [the integration report](experiments/0010-local-api-and-postgres-integration.md) and [ADR 0012](architecture/decisions/0012-local-research-api-and-immutable-postgres-evidence.md).
