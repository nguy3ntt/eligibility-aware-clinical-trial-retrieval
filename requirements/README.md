# Reproduction environments

Run installation commands from the repository root with Python 3.12 and a fresh virtual environment.

- `ci.txt` installs publishable offline tests plus lightweight database/vector HTTP integration dependencies. It does not download model weights or the TREC corpus.
- `research.txt` adds the existing local embedding, reranker and NLI runtime for the full experiment. Prepare pinned model snapshots separately with the documented pipeline commands.
- `observed-python312.txt` constrains the versions used in the Windows Python 3.12 research environment. It contains package names/versions only, no paths or credentials. Platform-specific dependencies not installed on Windows may still resolve on Linux; this is a constraints snapshot, not a universal hash-locked wheel bundle.

Use `python -m pip install -r requirements/ci.txt` for CI and `python -m pip install -r requirements/research.txt` for research. Run `python -m pip check` after installation. Exact frontend dependencies are recorded separately in `frontend/package-lock.json`; use `npm ci`.

Model weights, raw source archives, generated indexes and local database credentials remain excluded from Git. Reproducing the full benchmark requires the source hashes and model revisions in the release protocol, not merely a successful package installation. See the release operating guide for preparation and resource limits.
