# Scripts

Scripts will provide small reproducible wrappers around package entry points. Planned commands include:

- bootstrap the local environment;
- fetch a bounded sample;
- ingest canonical records;
- build or rebuild an index;
- run a named evaluation configuration;
- export a reviewed report.

Business logic must remain in Python packages rather than shell scripts.

`qdrant-local.ps1 -Action Start|Stop|Status` manages the optional pinned native Windows Qdrant server. The first start downloads and verifies the official executable; later starts work offline. It uses Windows extended storage paths, keeps data under ignored `qdrant_storage/`, and refuses to stop a recorded PID belonging to another executable. Use from PowerShell; it starts a hidden background process, not a Windows service. See [the operating guide](../docs/local-vector-storage.md).
