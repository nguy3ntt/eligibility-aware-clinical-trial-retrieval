# Data boundary

This repository stores data-processing code and small synthetic fixtures, not large generated datasets.

- `raw/`: immutable source snapshots exactly as received.
- `interim/`: reproducible normalized or partially transformed outputs.
- `processed/`: retrieval-, model-, or evaluation-ready derived data.

Large files under these directories are ignored by Git. Each stage has its own README describing its contract.

Never place real patient information anywhere in this project.
