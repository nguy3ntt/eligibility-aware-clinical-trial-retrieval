# Dense, sparse, and hybrid retrieval on a bounded diagnostic

Date: 2026-09-05. **Hybrid improves candidate recall but does not improve average top-10 ranking quality over dense search. Dense remains the default.** This is a diagnostic finding, not an official TREC benchmark or a medical eligibility result.

## Frozen comparison

The same 443 historical trials, title/condition representations, and 50 synthetic TREC 2022 topics are used for all methods. Metrics restrict the 35,394 source judgments to 1,511 judgments within this query-balanced pool. Unjudged pairs receive zero gain; missing judgments do not establish irrelevance. Grades 0/1/2 are source labels, not new assessments. The earlier full-corpus BM25 experiment remains the lexical baseline, but its metrics cannot be compared directly with this restricted pool.

Dense uses the pinned MiniLM model and normalized 384-dimensional vectors from `dense-m3-minilm-v1`. The artifact manifest SHA-256 is `f66e32d568983d2061db23a92e2d781f8f46f69030f965cf901c4623792f7480`. Sparse uses 2,814 vocabulary dimensions, Lucene BM25 (`bm25s 0.3.11`, `k1=1.2`, `b=0.75`), English stopwords, lowercasing, and no stemming. Qdrant 1.19.0 stores both named vectors in the separate `trials_hybrid_v1` collection. RRF uses equal branch weights and constant 60, fixed before observing these results.

Both branches apply identical artifact and optional age/sex filters. Exact dense retrieval isolates fusion from ANN approximation. Retrieve the bounded corpus, sort numeric score ties by trial ID, retain 100 candidates per branch, and fuse up to 100 results. Sparse returns positive lexical matches only, never zero-score padding. Each returned result preserves branch rank, raw score, fusion contribution, and source evidence.

Local machine-readable evidence: `evaluation/reports/m5-hybrid-replay/experiment.json`, six run/metric files, and two provenance files. Source/code/model hashes identify this uncommitted implementation; no nonexistent commit identifier is claimed. The earlier `m5-hybrid-final` run supplies a separate post-restart comparison. Generated evidence and model/index files remain ignored; this reviewed summary is public documentation.

## Aggregate results

Higher values are better. Recall@100 counts both positive relevance grades; it is not a confirmed-eligibility rate.

| Filter | Method | nDCG@10 | Recall@100 | MRR | Precision@10 |
|---|---|---:|---:|---:|---:|
| None | Dense | 0.5544 | 0.8720 | 0.7879 | 0.4040 |
| None | Sparse | 0.3268 | 0.7366 | 0.5311 | 0.2520 |
| None | Hybrid | 0.5234 | 0.9159 | 0.7764 | 0.3820 |
| Age/sex | Dense | 0.5584 | 0.7518 | 0.8035 | 0.3720 |
| Age/sex | Sparse | 0.3823 | 0.6217 | 0.6321 | 0.2620 |
| Age/sex | Hybrid | 0.5377 | 0.7847 | 0.8199 | 0.3620 |

Without demographics, hybrid gains 0.0439 Recall@100 but loses 0.0310 nDCG@10 versus dense: 22 topic wins, 27 losses, one tie. With demographics, recall gains 0.0329 and nDCG loses 0.0206: 23 wins, 26 losses, one tie. Filtered hybrid exceeds sparse nDCG by 0.1555, with 41 wins and nine losses. Filtering can lower pooled recall because it removes source grade-1 relevant-but-excluded trials, not just unrelated trials. Do not interpret cross-filter recall changes as a clean ranking ablation.

## Reviewed gains and failures

These are observations of stored rankings and source judgments, not new clinical conclusions. The explanations of why lexical terms helped or hurt are qualitative inferences, not learned eligibility rationales.

- **Topic 29, gain:** filtered nDCG@10 rises by 0.3716. `NCT03325374` (source grade 2) moves from dense rank 2 to hybrid rank 1, supported by sparse rank 1. `NCT03762174` (grade 2) moves from 4 to 3. The back/leg-pain wording provides useful lexical support in this case.
- **Topic 11, gain:** filtered nDCG rises by 0.3234. `NCT02301481` (grade 2, gastric adenocarcinoma trial) moves from dense rank 7 to hybrid rank 1, supported by sparse rank 4. Dense's first result is source grade 0. Specific condition wording helps here.
- **Topic 8, loss:** filtered nDCG falls by 0.6360. Dense's first trial `NCT02857205` (grade 2) disappears from hybrid's top 10. Fusion promotes `NCT02415361`, an unjudged trial for this topic, from dense rank 14 to hybrid rank 2 through sparse rank 2. Generic infant/parent wording appears to distract the lexical branch; this illustrates why a strong branch score is not a medical match.
- **Topic 18, loss:** filtered nDCG falls by 0.4398. Dense's first two candidates `NCT01447381` and `NCT00277433` leave hybrid's top 10; `NCT04364711`, unjudged for this topic, moves from dense rank 12 to hybrid rank 3 through sparse rank 1. Both-branch agreement can displace useful dense-only candidates when common narrative terms dominate.

## Correctness and limits

All 100 topic/filter combinations passed independent dense-matrix and BM25-library comparisons: 200 branch checks. Maximum absolute score errors were approximately `1.14e-7` dense and `2.38e-6` sparse, below the declared `1e-6`/`1e-5` tolerances. Numeric near-ties are allowed in reference verification; database results themselves sort exact score ties deterministically. Every vector and payload survived a server restart and full verification. Repeated imports retained 443 points.

The two post-restart evaluations produced byte-identical files for all six rankings and identical aggregate metrics. Final recorded source hashes match the evaluated implementation. All 129 publishable tests passed, including three isolated live-server tests; lint, formatting, and compilation passed. One existing Starlette/httpx deprecation warning remains. Manual load/verify/search commands passed in all three modes, confirmed the dense default, and rejected four invalid requests. The original dense-only collection still verifies unchanged.

This pool was chosen with judgments and is not held out. One of 50 synthetic queries is truncated by the dense encoder; sparse uses its full text. No parameter tuning, statistical significance, performance improvement, or full-corpus superiority is claimed. Sparse full-corpus scaling, held-out retrieval evaluation, richer patient extraction, criteria verification, API search, and a UI remain outside this implementation. The working engineering deliverables do not imply that the hybrid ranking-promotion gate has passed.

Reproduction and manual inspection commands are in [the operating guide](../hybrid-retrieval.md).
