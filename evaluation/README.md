# Evaluation

Evaluation is a first-class subsystem, not a notebook added after implementation.

## Data

- synthetic patient topics;
- qrels with irrelevant, excluded, and eligible labels;
- tiny synthetic fixtures safe for tests;
- immutable experiment manifests.

## Implemented baseline

Milestone 2 implements BM25 over three versioned trial representations:

- title, official title, and conditions;
- those fields plus summaries, detailed description, and interventions; and
- those fields plus the original eligibility text.

Each representation is evaluated with and without a conservative deterministic age/sex compatibility filter. The filter removes only explicit contradictions; missing or unparsed values remain candidates. It is a retrieval ablation and does not assess eligibility.

Dense exact retrieval, HNSW, hybrid retrieval, reranking, and criterion-aware systems remain future work.

## Metrics

The implemented retrieval metrics are nDCG@5/10 with linear TREC-grade gain, MRR, Precision@10, Recall@100, Success@5, and separate grade-2 and grade-1 recall at 100. See `docs/evaluation.md` for interpretation.

## Experiments

Every experiment records data, code, model, representation, index, filter, and random-seed versions. Reports must include per-query error analysis and negative results.

Generated reports are ignored by Git unless a deliberately reviewed release report is added.

## Run the baseline

After the historical corpus gate has passed, render the retrieval documents:

```bash
python -m pipelines.render_trials \
  --run-id trec-ct-2021-20210427 \
  --validation-id trec-ct-2021-20210427-validation-v2 \
  --output-id trec-ct-2021-render-v1
```

Run the six BM25 configurations with official synthetic topics and qrels from a saved inspection snapshot:

```bash
python -m evaluation.run_bm25 \
  --documents-id trec-ct-2021-render-v1 \
  --topics data/raw/<inspection-run-id>/topics2022.xml \
  --qrels data/raw/<inspection-run-id>/qrels2022.txt \
  --output-id bm25-trec2022-reproduction
```

Every output directory is new and local. It contains indexes, TREC run files, aggregate and per-query metrics, extracted topic demographics, hashes, package versions, parameters, and the selected configuration. See the reviewed [baseline report](../docs/experiments/0002-bm25-baseline.md).
