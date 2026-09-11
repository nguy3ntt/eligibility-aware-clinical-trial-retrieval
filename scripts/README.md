# Scripts

Scripts will provide small reproducible wrappers around package entry points. Planned commands include:

- bootstrap the local environment;
- fetch a bounded sample;
- ingest canonical records;
- build or rebuild an index;
- run a named evaluation configuration;
- export a reviewed report.

Business logic must remain in Python packages rather than shell scripts.

`frontend-local.ps1 -Action Start|Stop|Status` manages the React/Vite workspace on loopback port 5173 with a hidden Node process. It requires locked frontend dependencies to be installed first, checks process ownership before stopping, and never changes evidence or starts other services. See [the browser walkthrough](../docs/research-workspace.md).

`postgres-local.ps1 -Action Start|Stop|Status` uses installed PostgreSQL 17 binaries for a separate project-owned cluster on loopback port 55432. It keeps data under ignored `artifacts/postgres-local/` and generated credentials in ignored `.env.api.local`, without altering the installed Windows service. `api-local.ps1 -Action Start|Stop|Status` manages the loopback API on port 8000 with one worker and disabled access logs, verifying process ownership before stopping it. See [API setup and manual checks](../docs/local-research-api.md). These wrappers do not automatically migrate or import data.

`qdrant-local.ps1 -Action Start|Stop|Status` manages the optional pinned native Windows Qdrant server. The first start downloads and verifies the official executable; later starts work offline. It uses Windows extended storage paths, keeps data under ignored `qdrant_storage/`, and refuses to stop a recorded PID belonging to another executable. Use from PowerShell; it starts a hidden background process, not a Windows service. See [the operating guide](../docs/local-vector-storage.md).
