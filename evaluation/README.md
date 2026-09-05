# Evaluation

## Local Qdrant verification

`python -m evaluation.qdrant_smoke --topics data/raw/<inspection-run-id>/topics2022.xml --output-id <fresh-report-id>` verifies stored evidence and compares exact Qdrant results with a direct NumPy reference for every supplied synthetic topic, with and without conservative demographics filtering. Scores must agree within `1e-6`; ordered ID agreement is also reported because boundary ties may differ. This is a bounded correctness check, not an ANN or full-corpus relevance benchmark. Run `evaluation/tests/test_qdrant.py` offline, or set `QDRANT_TEST_URL=http://127.0.0.1:6333` to include its isolated real-server test. That test creates and deletes only a randomly named test collection.

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

Bounded dense exact and HNSW retrieval are available for operational testing. Full-corpus dense evaluation, hybrid retrieval, reranking, and criterion-aware systems remain future work.

## Metrics

The implemented retrieval metrics are nDCG@5/10 with linear TREC-grade gain, MRR, Precision@10, Recall@100, Success@5, and separate grade-2 and grade-1 recall at 100. See `docs/evaluation.md` for interpretation.

## Experiments

Every experiment records data, code, model, representation, index, filter, and random-seed versions. Reports must include per-query error analysis and negative results.

Generated reports are ignored by Git unless a deliberately reviewed release report is added.

## ANN and recovery checks

`python -m evaluation.qdrant_ann --topics data/raw/<inspection-run-id>/topics2022.xml --output-id <fresh-id>` compares HNSW efforts 10/32/128 with exact neighbors on identical vectors and filters. It validates the exact reference, measures paired warm HTTP latency, and rejects telemetry that indicates scans or concurrent activity. Recall is neighbor agreement, not relevance or eligibility. Run `pipelines.qdrant_index configure-ann` first. `evaluation.qdrant_recovery_smoke` checks source-text re-encoding and original/restored/rebuilt collections. Full commands and measurement limits are in [the operating guide](../docs/local-vector-storage.md#approximate-search-and-evaluation).

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

## Bounded dense retrieval

The current dense workflow operates on at most 512 historical trials. It validates model and data handling before full-corpus evaluation. It does not calculate TREC relevance metrics, apply dense age/sex filtering, or determine eligibility.

Prepare the two models and sample indexes using the [pipeline commands](../pipelines/README.md#bounded-dense-preparation). To search an already saved index with an official synthetic topic:

```bash
python -m evaluation.dense_search --index-id dense-minilm-v2 --topics data/raw/<inspection-run-id>/topics2022.xml --topic-id 15 --top-k 3
python -m evaluation.dense_search --index-id dense-pubmedbert-v2 --topics data/raw/<inspection-run-id>/topics2022.xml --topic-id 15 --top-k 3
```

Output includes `status=complete`, `documents_searched`, ordered NCT IDs, cosine scores, titles, model identity, and trial provenance. `eligibility_assessment=not_performed` and `benchmark_metrics_permitted=false` are intentional. A cosine score is not an eligibility probability. There is no arbitrary patient-text entry point; use synthetic TREC topics only. A small sample may contain no relevant trial for a topic, so a successfully executed search can still return poor matches.

All scores come from exact normalized-vector dot products, with stable NCT-ID tie-breaking. The search checks all sample documents in blocks, without a vector database or approximate index. Query encoding must match the saved model revision, snapshot, dimensions, normalization, and prompt. Damaged files or mismatched models fail before returning results.

Run the real-model functional verifier with a fresh report ID:

```bash
python -m evaluation.dense_smoke --index-id dense-minilm-v2 --topics data/raw/<inspection-run-id>/topics2022.xml --output-id dense-minilm-manual-check
python -m evaluation.dense_smoke --index-id dense-pubmedbert-v2 --topics data/raw/<inspection-run-id>/topics2022.xml --output-id dense-pubmedbert-manual-check
```

Expected output: `status=passed`, three synthetic query checks, and eight self-retrieval checks. The verifier repeats encodings and rankings, compares blockwise results with a direct full-matrix reference, and re-encodes saved documents to check document/query consistency. Detailed output stays under ignored `evaluation/reports/`.

`python -m pytest evaluation/tests/test_dense_retrieval.py` runs offline tests with invented fixtures and no model download. Install the `dense` extra to run every dense test; unavailable optional dependencies cause the relevant tests to be skipped. The API still exposes only foundation endpoints; dense searching currently uses the command line.
