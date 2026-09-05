# Experiment 0003: Bounded dense retrieval smoke test

- Date: 2026-09-03
- Scope: local embedding and exact-search correctness on a small historical sample
- Corpus input: the validated 375,580-trial April 27, 2021 render
- Sample: 256 trials selected by the lowest `SHA256("dense-smoke-v1:" + NCT_ID)` values
- Selection uses no topics or judgments; benchmark scoring is prohibited for these artifacts
- Final artifacts: `dense-minilm-v2`, `dense-pubmedbert-v2`; detailed smoke reports remain local

## What was tested

The pipeline revalidated the entire rendered input, including file and row hashes, row count, stable NCT IDs, and uniqueness. It preserved source provenance for the selected trials and encoded the same `summary` representation with two pinned local models. The template contains titles, conditions, summaries, detailed description, and interventions, with no added prompt or chunking.

The [model decision](../architecture/decisions/0004-pin-local-dense-encoders.md) records full revisions, licenses, dimensions, token limits, and download safeguards. Inference used CPU, four threads, batches of 16, float32 values, L2 normalization, a fixed seed, and local files only. The final replay explicitly disabled hub/transformer network access as well.

The three official synthetic topics 1, 15, and 38 were searched with each model. No qrels were used to score or select results. Each query was repeated, blockwise exact search was checked against direct full-matrix dot products, and eight saved documents per model were re-encoded to check document/query consistency.

## Results

| Measure | MiniLM | PubMedBERT Embeddings |
|---|---:|---:|
| Encoded trials | 256 | 256 |
| Vector dimensions | 384 | 768 |
| Model token limit | 256 | 512 |
| Truncated trial inputs | 160 (62.5%) | 55 (21.5%) |
| Final replay encoding time | 5.47 s | 104.06 s |
| Final replay throughput | 46.76 trials/s | 2.46 trials/s |
| Raw vector payload | 393,216 bytes | 786,432 bytes |
| Repeated synthetic query checks | 3/3 passed | 3/3 passed |
| Full-matrix reference checks | 3/3 passed | 3/3 passed |
| Document self-retrieval checks | 8/8 passed | 8/8 passed |
| Full encoding replay byte-identical | yes | yes |

Both models succeeded operationally. Maximum absolute vector differences for repeated queries were zero in this environment, and the checked search scores exactly matched the reference. Two complete encodings per model produced identical saved vector files. This does not guarantee byte-identical output across different operating systems, numerical libraries, or hardware; the manifests record the tested runtime.

The first encoding took 5.20 seconds for MiniLM and 77.30 seconds for PubMedBERT. The variation between runs means these are local preparation measurements, not a controlled latency benchmark or a reliable full-corpus time estimate. Encoding time excludes model download/loading and final artifact serialization. Vector payload sizes exclude model weights, document metadata, and the NumPy file header.

## Important limitations

This is a deliberately small, query-independent sample. It can contain no relevant trial for a synthetic topic; a correctly executed search can therefore return poor matches. No relevance metric, biomedical-model advantage, dense/BM25 superiority, clinical eligibility determination, or current recruitment claim is established.

Truncation is substantial. Both models keep the beginning of the input and discard tokens beyond their respective limits. Every affected trial is recorded in an encoding audit. Longer model context reduced observed truncation, but the tokenizers also differ, so these counts are not a controlled model-quality comparison. Before full-corpus evaluation, the project must explicitly choose and compare long-document input policies and match BM25/dense fields fairly.

Dense retrieval currently has no age/sex filter, criterion verifier, vector database, ANN index, API search endpoint, or browser interface. Search returns source-linked candidates and a cosine-similarity score, not an eligibility probability. Outputs require professional review.

## Reproducibility and checks

- Full rendered input SHA-256: `a7b133735968d60aa9562bdb8bf8a918345ce7302b12d66393f974cfe80dd84e`.
- Sample documents SHA-256: `90240fb460b96879004188da5f5f8a54fdd4e3e3d704bd3bf1fa4863d4d36539`.
- MiniLM vectors file SHA-256: `54425cf86b16a39bf97763473b24d65d5a0603a13306c722271b995db620fac2`.
- PubMedBERT vectors file SHA-256: `e077818234091e8e42a1960a1cb86333c210db131df3e039c033576badf6b503`.
- Runtime: Python 3.12.13, sentence-transformers 5.7.0, transformers 5.16.1, torch 2.13.0, NumPy 2.5.2, huggingface-hub 1.29.0, safetensors 0.8.0; Windows 11, Intel CPU.
- Base Git commit: `41f7079`; exact working-source hashes accompany each index because the new code was not committed during the experiment.
- All 80 publishable repository tests passed with the installed extras. The existing local inspection-verification tests bring this checkout's total to 94. Lint, formatting, compilation, and Git whitespace checks passed. One pre-existing Starlette dependency deprecation warning remains.

Models, samples, vectors, per-trial text/audits, and detailed reports stay ignored. This reviewed aggregate report and the implementation are the intended public artifacts. See the [preparation guide](../../pipelines/README.md#bounded-dense-preparation) and [manual search/check commands](../../evaluation/README.md#bounded-dense-retrieval).

## Milestone 3 comparison

A final controlled diagnostic selected up to three records per topic and judgment grade, retaining all available records when a grade had fewer than three. This produced 443 unique trials across all 50 synthetic topics. MiniLM, PubMedBERT, and BM25 searched exactly the same title-and-condition text, with and without the deterministic age/sex filter. No document input was truncated.

| System | Filter | nDCG@10 | MRR | P@10 | R@100 |
|---|---|---:|---:|---:|---:|
| BM25 | none | 0.3268 | 0.5311 | 0.252 | 0.7443 |
| BM25 | age/sex | 0.3823 | 0.6321 | 0.262 | 0.6852 |
| MiniLM | none | 0.5544 | 0.7879 | 0.404 | 0.8720 |
| MiniLM | age/sex | **0.5584** | **0.8035** | 0.372 | 0.7518 |
| PubMedBERT | none | 0.4999 | 0.7517 | 0.350 | 0.8681 |
| PubMedBERT | age/sex | 0.5163 | 0.7777 | 0.342 | 0.7370 |

MiniLM with filtering had the highest nDCG@10 in this pool, while unfiltered MiniLM had higher Precision@10 and Recall@100. PubMedBERT did not outperform MiniLM here despite being much slower in the earlier resource test. The age/sex filter improved early ranking but reduced recall, especially for grade-1 excluded trials. These are development-pool observations: qrels constructed the candidate pool, so the numbers are optimistic and cannot be compared with the full-corpus BM25 figures or presented as official TREC performance.

This evidence selects MiniLM as the model carried into ANN development. A full-corpus exact-versus-ANN check remains mandatory in Milestone 4, and the official full-corpus benchmark remains a release requirement.
