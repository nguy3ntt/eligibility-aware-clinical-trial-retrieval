# Guided setup verification

Date: 2026-10-19. Decision: [ADR 0019](../architecture/decisions/0019-guided-read-only-setup.md).
Usage and manual checks: [setup guide](../setup.md).

## Scope

This is engineering verification of the requested setup improvement, not a retrieval
experiment or clinical validation. The standard-library checker separates fixture-test,
interactive-app and full offline benchmark prerequisites. It diagnoses requirements
without provisioning infrastructure, modifying evidence or running model inference.

The working tree is based on commit `35f876cc4b7069a2909cf6ab19a4fdc4671c4adf` with
uncommitted screening-coverage and setup changes. The existing corpus, models, database,
indexes and application defaults were reused unchanged. Source and raw diagnostic
reports are local; credentials and source narratives are excluded from checker output.

## Observed checks

| Check | Result |
|---|---|
| Fixture-test profile | Four checks passed; no models, Node or services required |
| App profile, offline | File/metadata checks passed; services explicitly not checked |
| App profile, online with full verification | All 15 checks passed |
| Full benchmark profile with full verification | All eight checks passed |
| New isolated setup tests | 26 passed |
| Complete offline Python suite | 522 passed, 13 opt-in integrations skipped |
| Repository Python lint, format and compilation | Passed |

App verification checked pinned model snapshots without loading weights; direct
frontend dependency versions; all 443 index rows/vectors and their source evidence;
50 official synthetic topics; the database migration and checksummed 51-case/446-trial
catalog; Qdrant 1.19.0 and its catalog contract; API dependency readiness; and the local
Vite response. The full benchmark check read the frozen 375,580-trial source/index,
all five XML archive hashes, original 2022 topics/judgments and recorded query/document
runtime identity. It did not reacquire cases or judgments or rerun any metrics.

Local reports: `artifacts/setup-check-app.json`, `artifacts/setup-check-benchmark.json`
and `evaluation/reports/setup-check-regressions.xml`. These generated files stay ignored.
One existing FastAPI/HTTPX test-client deprecation warning remains in the offline suite.

## Failure and safety checks

Invented fixtures exercise missing packages before site-packages are available,
missing or corrupted pinned model files, mismatched source/index evidence, incompatible
benchmark model/runtime identity, frontend dependency drift, service outages and
invalid readiness responses. A temporary loopback HTTP server verifies that redirects
are rejected and environment proxies are ignored. Additional tests reject unsafe paths
and nonlocal URLs, prevent exception secrets from entering reports, preserve optional
model warnings and verify PowerShell argument forwarding and exit codes.

## Limits

Passing setup checks is not proof of successful model inference or browser rendering.
Package presence does not prove all binary imports or transitive dependency consistency;
the guide separately requires `pip check` and appropriate tests. Frontend lock checks
cover direct installed package versions, not every transitive file. Without `--verify`,
most artifact checks inspect metadata and presence rather than hashing every file.

The fresh-install sequence assembles the existing public preparation commands. A second
complete machine/install/download reproduction was not performed for this change.
Cross-platform artifact identity may require rebuilding under the destination runtime.
No frontend behavior, research metrics, model promotion or deployment is claimed.
