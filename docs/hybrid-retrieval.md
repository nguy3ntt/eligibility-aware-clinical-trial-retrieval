# Local hybrid retrieval

This command-line workflow compares semantic dense retrieval, lexical BM25 retrieval, and Reciprocal Rank Fusion (RRF). It uses public historical trials and synthetic TREC topics only. Results are potential matches requiring professional review, never confirmed eligibility. The API search route and graphical interface are not implemented yet.

## Prerequisites

Run commands from the repository root in your Python environment. Install `pip install -e ".[dev,hybrid]"` if needed. Use local Qdrant 1.19.0 as described in [the storage guide](local-vector-storage.md). On the existing Windows workspace the environment is in `../.venv`; `scripts/qdrant-local.ps1 -Action Start` starts the already prepared native server. The dense source artifact and pinned MiniLM model must already exist locally; these commands do not download models or data.

The defaults use `data/processed/dense-m3-minilm-v1` and the separate collection `trials_hybrid_v1`. The artifact has 443 trials with 384-dimensional normalized title/condition embeddings. Preparation and validation are described in the [dense diagnostic report](experiments/0003-bounded-dense-smoke.md). This pool was selected using judgments; it is not a full-corpus benchmark.

## Load and check

```bash
python -m pipelines.hybrid_index load
python -m pipelines.hybrid_index verify
```

Expected: `status: verified`, `points: 443`, `sparse_vectors_verified: 443`, `vocabulary_size: 2814`, and `payload_indexes: 5`. Loading the same artifact again is safe and retains 443 points. Verification compares every payload, dense vector, sparse dimension/weight, and collection contract. Corruption or a different artifact/model/tokenizer fails visibly. Do not run competing imports, searches, recovery, or evaluations while modifying a collection.

For a rebuild, run `load --collection <new-name>`, then `verify --collection <new-name>`. This derives both vector types from the verified artifact and leaves the existing collection untouched. A previously existing collection is reused only if its contract and vector configuration match. The earlier dense-only snapshot/rebuild commands do not constitute sparse verification.

## Search and inspect provenance

Replace `<inspection-run-id>` with your saved synthetic-topic snapshot; the existing workspace uses `m1-20260831-500-v2`.

```bash
python -m pipelines.hybrid_index search --topics data/raw/<inspection-run-id>/topics2022.xml --topic-id 29 --method hybrid --top-k 5
python -m pipelines.hybrid_index search --topics data/raw/<inspection-run-id>/topics2022.xml --topic-id 29 --method dense --top-k 5
python -m pipelines.hybrid_index search --topics data/raw/<inspection-run-id>/topics2022.xml --topic-id 29 --method sparse --top-k 5
```

The default method is `dense`, the default filter is `age_sex`, and dense queries use exact search. Add `--filter none` to compare unfiltered results. Both branches receive the same filters. Missing demographic facts remain unknown and do not create exclusion filters; retaining a trial does not establish eligibility. Only age/sex filtering exists at this stage.

Inspect `results[].trial_id`, `payload.source`, `payload.content_sha256`, and `branches`. Hybrid results expose each contributing branch's one-based rank, `raw_score`, `score_kind`, and `rrf_contribution`. A dense rank of 2 and sparse rank of 1 contribute `1/62 + 1/61`, approximately `0.03252247`. Raw cosine and BM25 scores are never added together. Single-branch output labels its original score and omits RRF contributions. The score is not a probability.

With the current artifact, filtered topic 29 ranks `NCT03325374` first under hybrid (dense rank 2, sparse rank 1). This is a reproducibility check, not a medical recommendation. Try topic 8 as a documented case where fusion worsens the ranking. Sparse queries with no known vocabulary return no lexical candidates; hybrid then uses dense candidates only. `query_truncated` and lexical query diagnostics remain visible.

## Reproduce the comparison

```bash
python -m evaluation.hybrid --topics data/raw/<inspection-run-id>/topics2022.xml --qrels data/raw/<inspection-run-id>/qrels2022.txt --output-id hybrid-manual-01
```

Use a fresh output ID each time. Expected: `status: complete`, six systems (three methods times two filters), and comparisons that explicitly show hybrid does **not** exceed dense mean nDCG@10. The report directory contains six `.run` files, six aggregate/per-topic metric files, two detailed provenance files, and `experiment.json` with contracts, hashes, parameters, and independent reference checks. A failure leaves `failure.json` and no successful experiment manifest. Reports stay Git-ignored.

Run `python -m pytest evaluation/tests/test_hybrid.py` for offline scoring/failure tests. Set `QDRANT_TEST_URL=http://127.0.0.1:6333` in your shell to also enable the live integration test. It creates and deletes only its own randomly named test collection. The full repository suite checks earlier functionality too.

## Current result and limits

See [the reviewed ablation](experiments/0005-bounded-hybrid-ablation.md). Hybrid improves top-100 recall but reduces average top-10 ranking quality versus dense. This is why dense remains the default. No significance, production latency, full-corpus superiority, or medical eligibility claim is justified. One synthetic query exceeds MiniLM's 256-token limit. Lexical search uses the full narrative; the different query capacity is recorded rather than hidden. Future evaluation must revisit this limitation independently of the judged diagnostic pool.

