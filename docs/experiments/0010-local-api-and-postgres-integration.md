# Local API and PostgreSQL integration

Date: 2026-09-11. Outcome: bounded engineering integration passed. This is not a new retrieval benchmark or clinical-validation result. The final verified worktree is based on user-created commit `3c6431ea0a5760896a31d3586cf6a243809a15ac`, with remaining documentation and test-output configuration changes uncommitted. Saved responses record executable-code fingerprints and runtime identities. The assistant did not commit or push.

## Scope and configuration

FastAPI `/v1` now exposes search, screening, synthetic case/trial lookup and bounded experiment execution/inspection. PostgreSQL persists immutable source catalogs and completed operations; explicit Alembic migrations and transactional imports own four tables. Case inputs are curated IDs only, not arbitrary patient narratives. Source lookup retains full evidence. Search defaults remain exact dense with legacy age/sex filters; sparse/hybrid/profile filtering/reranking are opt-in, and screening NLI advisories never change deterministic outcomes.

The initial `bounded-api-v1` catalog contains 51 synthetic cases and 446 trials: 50 official TREC 2022 cases plus one invented case, and 443 historical trial records plus three invented demonstrations. Catalog SHA-256: `d8f9cc2755f193e6e96f48efeaa7c83d5d81aee45455e8d6acc6539f347823c7`. The existing `dense-m3-minilm-v1` artifact and `reranking-evidence-v1` source evidence remain unchanged. Default API search uses the exact dense branch of the existing `trials_hybrid_v1` collection.

Verification used actual PostgreSQL 17.6, Qdrant 1.19.0 and pinned local models, not SQLite or mocked production storage. PostgreSQL was already installed; a separate project-owned loopback cluster was initialized without changing the installed Windows service. The existing database extra supplies SQLAlchemy 2.0.52, psycopg 3.3.5 and Alembic 1.19.2 in this environment. One API worker serializes expensive operations and returns 429 for overlap. Models load lazily; there is no deployment, throughput or first-request latency claim.

## Results

| Check | Result |
|---|---|
| Full local regression suite | 386 passed, including private local checks |
| Publishable regression suite | 372 passed; 35 new API/database tests |
| Actual PostgreSQL tests | Six passed: migrations/model agreement, repeat imports/conflicts/rollback, tamper detection, isolated migration downgrade/upgrade, persisted operations, complete API with Qdrant/models |
| Actual HTTP checklist | 24 passed in each of three runs, including after service restarts |
| Dense correctness | API IDs and scores matched an independent exact vector calculation, absolute score tolerance 1e-6 |
| Authored screening evaluation through HTTP | 34/34 exact invented pairs, 41 criteria |
| Index preservation | Dense 443, hybrid 443 including sparse vectors, criteria 139; full evidence/vector verification passed |
| Static checks | Ruff lint/format, Python compilation and Compose configuration passed |

Eight upstream deprecation warnings remain (Starlette test transport and Torch scripting). The test suite exercises malformed/oversized requests, immutable conflicts, missing/corrupted source records, strict parameter validation, busy operations and non-reflecting failures. Rollback tests create/drop only uniquely named test schemas. Existing Qdrant tests use disposable collections.

Real service-stop checks confirmed PostgreSQL outage leaves liveness at 200 but readiness at 503. During a Qdrant outage, readiness and fresh search returned 503 while a saved identical search returned 200 with `replayed: true`. API and database restarts retained saved operations. Identical default search for `trec-ct-2022:29` retained the same operation ID and complete result across all three HTTP reports, with current code matching stored fingerprints. Result SHA-256: `23fc59ef8ef6a1c10da6ac02d781f4bdf55c0d04f540242a718565edaa81289c`.

The first resumed publishable test attempt encountered stopped dependencies and failed five Qdrant tests plus six PostgreSQL setups; restoring the project services resolved those failures. A third-party test traceback exposed the local development database credential. It was rotated without publishing the replacement, the API was restarted, and pytest now defaults to short tracebacks to avoid connection-frame argument dumps. This was a test diagnostic issue; fixed API failure envelopes and server-log privacy checks passed.

Ignored local evidence: `evaluation/reports/m10-http-initial/`, `m10-http-release/`, `m10-http-resumed-final/`, `m10-handoff-verification.json` and `m10-tests-final.xml`. Reviewed documentation may be published; raw/generated data, credentials, models, database files, reports and private milestone tracking remain ignored.

## Interpretation and limitations

The complete HTTP request/persistence path and structured failures work with actual dependencies. Replayed results are explicitly stored historical operations, not fresh searches. HTTP experiment execution deliberately supports only a fixed bounded authored evaluation; historical report imports retain their original meaning and do not rerun/promote models.

No prior research gate changes: the reranker still underperforms the dense diagnostic, hybrid promotion and full-corpus/held-out validation remain unearned, and all 150 previously explained historical pairs remain insufficient information. Invented screening success does not establish broad clinical coverage. The local API has no authentication, real-patient input or cloud deployment and must not be exposed to the internet. The installed PostgreSQL version was not upgraded or qualified for deployment. React remains subsequent work.

See [operating and manual tests](../local-research-api.md) and [ADR 0012](../architecture/decisions/0012-local-research-api-and-immutable-postgres-evidence.md).
