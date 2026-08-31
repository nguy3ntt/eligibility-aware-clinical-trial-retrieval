# Evaluation

Evaluation is a first-class subsystem, not a notebook added after implementation.

## Data

- synthetic patient topics;
- qrels with irrelevant, excluded, and eligible labels;
- tiny synthetic fixtures safe for tests;
- immutable experiment manifests.

## Baselines

- BM25;
- dense exact retrieval;
- structured-filter baseline;
- later HNSW, hybrid, reranked, and criterion-aware systems.

## Metrics

Retrieval metrics, eligibility-classification metrics, ANN recall, latency, storage, and throughput are computed separately. See `docs/evaluation.md`.

## Experiments

Every experiment records data, code, model, representation, index, filter, and random-seed versions. Reports must include per-query error analysis and negative results.

Generated reports are ignored by Git unless a deliberately reviewed release report is added.
