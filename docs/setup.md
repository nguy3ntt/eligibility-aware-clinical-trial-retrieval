# Guided local setup

Choose the environment you need before downloading anything:

| Goal | Checker profile | Required preparation |
|---|---|---|
| Run invented fixture tests | `tests` | Python and the lighter CI dependencies; no models, corpus, Node or running services |
| Use the browser application | `app` | Research dependencies, Node/npm, pinned MiniLM, bounded artifacts, PostgreSQL/Qdrant and the curated catalog |
| Reproduce the original offline experiment | `benchmark` | Research dependencies, pinned MiniLM/reranker, full frozen corpus/index and original cases/judgments; no running app services |

All commands run from the **nested Git repository**, the folder containing this guide's
parent `README.md`, `requirements/` and `frontend/`. Python 3.12 is the documented install
environment. The checker itself uses the standard library and can report missing packages
before the project is installed. It does not install, download, start services, migrate,
seed, modify configuration or run model inference.

See the [verification record](experiments/0014-guided-setup-verification.md) for tested
profiles, failure cases and the limits of the local checks.

## Check this prepared Windows workspace

```powershell
.\scripts\check-setup.ps1 -Profile app -Online -Verify
```

This selects the short sibling virtual environment used by the existing Windows
launchers. If it is absent, the wrapper looks for Python on PATH, excluding the Windows
Store shortcut. Supply `-Python 'C:\path\to\python.exe'` to inspect another environment;
that does not change which interpreter the existing API launcher uses.

The equivalent cross-platform Python command is:

```powershell
python -B -m pipelines.setup_check --profile app --online --verify
```

Without `--online`, no services are probed. Without `--verify`, local model/artifact
checks inspect metadata, presence and basic identity links; they do not hash every file.
`--verify` calls the existing authoritative validators, verifies model/index/source
hashes and aligns the app's model snapshot with its document index. It loads no weights.
For the full benchmark it also reads all vector shards, rendered bytes and five source
archives, so allow more time and disk activity.

Output states:

- **PASS:** that named check succeeded. Read its stated scope.
- **FAIL:** a required prerequisite is missing, incompatible, unavailable or invalid.
  Follow the numbered next steps and rerun the checker.
- **WARNING:** an optional app model is unavailable. Ordinary search needs MiniLM;
  reranking and NLI are opt-in. The fixed benchmark requires its reranker.
- **NOT_CHECKED:** the operation was outside the requested scope, such as service
  readiness during an offline check.

Exit code **0** means the selected checks passed; **1** means at least one required
check failed. JSON output is available with `--json` or PowerShell `-Json`. Redirect
local reports only into ignored `artifacts/` (create that folder first if absent), for example:

```powershell
python -B -m pipelines.setup_check --profile app --online --verify --json > artifacts/setup-app.json
```

The report does not echo connection strings, passwords, environment values, exceptions,
source narratives or server error bodies. Online checks use local database reads and
loopback HTTP only, with bounded responses, no proxy and no redirects.

## Install the fixture-test environment

From a new checkout, create a short virtual environment. The sibling location also
matches the native Windows app launchers:

```powershell
python -m venv ../.venv
```

Activate it using `..\.venv\Scripts\Activate.ps1` on Windows, or
`source ../.venv/bin/activate` on Linux/macOS. Then:

```powershell
python -m pip install -r requirements/ci.txt
python -m pip check
python -B -m pipelines.setup_check --profile tests
python -m pytest
```

The dependency files record the observed Python 3.12 environment. Package presence
does not prove binary importability or transitive compatibility: `pip check` and the
tests are separate checks. Model/service integration tests require their documented
opt-in flags. A fixture-test installation does not claim those integrations passed.

## Prepare the local application

If the app profile already passes with `--verify`, reuse the verified files. Do not
regenerate artifacts solely to follow this guide. The API catalog and vector contracts
are immutable; a new artifact cannot overwrite an existing catalog/collection identity.

For a **fresh installation**:

1. Install the research dependencies in the activated environment:
   `python -m pip install -r requirements/research.txt`, then `python -m pip check`.
2. Install Node 24.16+ and npm, then `npm --prefix frontend ci`. The checker compares
   the direct installed frontend versions with the lockfile. It does not replace npm's
   complete dependency integrity checks.
3. Prepare MiniLM with `python -m pipelines.dense prepare-model --model minilm`.
   Optional app features use `python -m pipelines.prepare_reranker` and
   `python -m pipelines.prepare_nli`. Those explicit preparation commands download
   pinned public weights; the checker never downloads them.
4. Prepare the source and bounded index below. These files are deliberately absent
   from GitHub. A successful package install or an empty database cannot replace them.
5. Start PostgreSQL/Qdrant, explicitly migrate/import verified evidence, and then
   start the API and frontend. The start commands below do not perform artifact preparation.

### Fresh source and bounded artifact preparation

The existing public pipeline can reconstruct the documented judgment-selected 443-trial
diagnostic. It requires the full historical corpus for source validation/rendering even
though the app searches only the bounded artifact. Allow roughly 15 GB free disk for
fresh source/models/dependencies and derived data; 16 GB RAM is a planning minimum,
32 GB recommended. See [release requirements](research-release.md) for the measured
environment. No GPU or paid inference API is needed.

Run this only when the named destinations do not exist. The first acquisition also
saves the official topics/qrels at the legacy path the API seed command expects.
`--limit 1` requests one public current-registry inspection record; that current record
is not used as historical benchmark evidence. The folder name is retained for compatibility.

```powershell
python -m pipelines.inspection fetch --run-id m1-20260831-500-v2 --limit 1
python -m pipelines.historical_corpus fetch --run-id trec-ct-2021-20210427
python -m pipelines.historical_corpus validate --run-id trec-ct-2021-20210427 --output-id setup-corpus-validation-v1 --qrels data/raw/m1-20260831-500-v2/qrels2022.txt
python -m pipelines.render_trials --run-id trec-ct-2021-20210427 --validation-id setup-corpus-validation-v1 --output-id trec-ct-2021-render-v1
python -m evaluation.run_dense_diagnostic prepare --documents-id trec-ct-2021-render-v1 --topics data/raw/m1-20260831-500-v2/topics2022.xml --qrels data/raw/m1-20260831-500-v2/qrels2022.txt --pool-id setup-diagnostic-pool-v1
python -m pipelines.dense encode --sample-id setup-diagnostic-pool-v1 --output-id dense-m3-minilm-v1 --model minilm --representation title_conditions --batch-size 32 --threads 4
python -m pipelines.rerank prepare-evidence --index-id dense-m3-minilm-v1 --evidence-id reranking-evidence-v1
python -B -m pipelines.setup_check --profile app --verify
```

Stop after any failing command; PowerShell does not automatically stop a pasted list
of native commands on nonzero exit. Preserve interrupted destinations. Use the existing
documented acquisition resume option where available; otherwise use fresh identities.
Do not remove working data or edit checksums to make the checker pass. Rebuilt artifacts
have new generation identities, even if their trial IDs/vectors agree.

These are the existing pipeline interfaces assembled into one guide. This extension
does not claim a second fresh-machine/full-download reproduction; its live checks reuse
the verified local source/model/index artifacts. Published-byte reproducibility and
research limitations remain documented in the release reports.

### Start the prepared Windows application

The native PostgreSQL launcher needs installed PostgreSQL 17 binaries at its documented
location. It creates a separate project cluster and ignored local credentials; it does
not change the installed Windows PostgreSQL service. Start the prepared services:

```powershell
.\scripts\postgres-local.ps1 -Action Start
.\scripts\qdrant-local.ps1 -Action Start
```

On a **new empty project database/vector store only**, run these explicit preparation
steps after the bounded artifacts exist:

```powershell
python -m pipelines.hybrid_index load
python -m pipelines.api_data migrate
python -m pipelines.api_data seed
```

Existing users with a ready immutable catalog should skip those steps. For a conflicting
catalog or collection, follow [API preparation](local-research-api.md) and
[hybrid preparation](hybrid-retrieval.md) with deliberately new identities.

```powershell
.\scripts\api-local.ps1 -Action Start
.\scripts\frontend-local.ps1 -Action Start
.\scripts\check-setup.ps1 -Profile app -Online -Verify
```

Open [the workspace](http://127.0.0.1:5173) and follow the
[manual browser walkthrough](research-workspace.md). The checker uses actual database
migration/catalog reads and the Qdrant contract; a listening port alone cannot pass.
API readiness remains distinct from model inference and browser rendering.

On Linux/macOS use the [Compose and API guide](local-research-api.md) with local
configuration, then the standard frontend command `npm --prefix frontend run dev`.
Native PowerShell service launchers target Windows. The Python checker is portable;
existing vector artifacts may require a rebuild on a different runtime/platform.

## Prepare the full offline benchmark

Follow [research-release.md](research-release.md) for the full render, pinned models
and sharded 375,580-trial index. Then run:

```powershell
python -B -m pipelines.setup_check --profile benchmark --verify
```

This checks the full original 2022 benchmark prerequisites, not an untouched evaluation
set. It verifies source/model/index files and recorded runtime compatibility; it does
not run metrics or consume the 2021 holdout again. PostgreSQL, Qdrant, Node and the web
servers are unnecessary for this offline profile. A mismatch needs a new index under
the new runtime, not a weakened identity check or edited manifest.

## Manual checker tests

1. Run the fixture profile. It should pass on the lightweight environment without
   starting services or downloading models.
2. Run the app profile with `--online --verify` on the prepared workspace. Expect
   **checks_passed** and pass rows for PostgreSQL, Qdrant, API and frontend. Optional
   model warnings are allowed when those optional features were not prepared.
3. Run the same app check without `--online`. Expect **NOT_CHECKED** for services;
   it must not claim they are ready.
4. Run `python -m pytest pipelines/tests/test_setup_check.py -p no:cacheprovider`.
   The isolated fixtures exercise missing dependencies, corrupt model bytes, mismatched
   artifacts, stale frontend dependencies, outages, safe output and wrapper exit codes.
   Do not delete your real model/data files to simulate a failure.
