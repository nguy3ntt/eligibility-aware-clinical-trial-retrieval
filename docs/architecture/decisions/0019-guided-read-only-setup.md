# 0019 — Guided read-only setup checks

Date: 2026-10-19. Status: accepted for requested improvement 3.

## Context

The system has lightweight fixture tests, a bounded interactive application and full
offline experiments, with different prerequisites. Existing launchers preserve service
ownership and data, but setup knowledge is spread across several guides. A fresh clone
can install packages successfully yet lack the model files, historical sources, index
and curated database evidence required by the application.

## Decision

Add standard-library entry point `python -B -m pipelines.setup_check` and a small
PowerShell interpreter-selection wrapper. Diagnostic business logic stays in Python.
The wrapper selects the existing short sibling environment or an explicitly provided
interpreter, restores the calling directory and preserves exit codes. It ignores the
Windows Store Python shortcut during automatic selection.

Profiles are `tests`, `app` and `benchmark`. The test profile requires no research
models, Node or services. The app profile checks the core MiniLM, bounded artifacts,
synthetic source and frontend/configuration; its reranker and NLI are optional warnings.
The fixed benchmark requires its reranker and full frozen source/index/runtime. It does
not require running application services. No extra dependency on an unused client library
is imposed beyond the existing declared installation route.

Default checks inspect presence, manifest identity links and direct frontend versions.
`--verify` reuses authoritative existing model/artifact/source validators and checks the
document/query model snapshot link. It verifies bytes without loading weights or running
inference. Full offline checks also validate the original cases/judgments, archives and
recorded query/document runtime fields. No dependency/model thresholds are relaxed.

`--online` opts into local database reads and loopback HTTP. Database readiness requires
the migration revision and checksum-validated 51-case/446-trial catalog, Qdrant requires
the recorded contract and pinned service version, and API readiness requires its actual
dependency response. A listening socket or HTTP 200 alone is insufficient. Frontend
response inspection does not claim successful rendering. All online checks have bounded
connections/responses, disable HTTP proxies/redirects and reject remote/credential URLs.

Reports distinguish pass, required failure, optional warning and not checked. Exit 0
means the selected setup checks passed; exit 1 means a required check failed. Reports
contain fixed, actionable next steps without credentials, environment values, arbitrary
exception strings, source narratives or server error bodies. JSON output is optional.
The checker performs no downloads, installs, migrations, catalog imports, model inference,
service starts/stops, configuration edits or data/index changes.

## Consequences

One [setup guide](../../setup.md) assembles the existing fresh-source, artifact, database
and service sequence. It corrects the virtual-environment path ambiguity and separates
prepared-workspace startup from fresh data preparation. Rebuilt artifact identities
remain distinct; the guide does not direct users to overwrite working catalogs.

Local fault tests use invented files/services. Current prepared app and full-benchmark
checks can validate real artifacts; a new complete machine/install/download reproduction
is not implied. Existing service ownership guards, research scope and defaults remain.
No deployment or new infrastructure is introduced; GitHub publication remains manual.
