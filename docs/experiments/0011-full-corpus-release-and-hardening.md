# Full-corpus retrieval release and local hardening

Date: 2026-09-12. Research scope: public frozen trials and synthetic TREC cases only.
Protocol: `full-trec-release-v1`. No model/default promotion or deployment.

## Question and design

How do fixed lexical, dense, fused and reranked retrieval configurations behave when the
candidate universe expands from the earlier 443-trial diagnostic to all **375,580** records
in the official April 27, 2021 corpus? All **50** official 2022 synthetic topics and
**35,394** judgments are used. Every judged trial is present. These topics have previously
been inspected; this is full-corpus evaluation, **not held-out validation**.

BM25 and MiniLM both receive brief title, official title and conditions. BM25 uses Lucene
scoring, k1=1.2, b=0.75, English stopwords and bm25s 0.3.11. MiniLM uses 384-dimensional
L2-normalized float32 vectors and exact dot products. The full reference agrees with an
independent blocked computation within 1e-6 for every query. Both branches produce depth
100 with stable NCT-ID ties. Hybrid is equal-weight reciprocal-rank fusion, constant 60,
branch depth 100. Age/sex uses the unchanged legacy extractor and deterministic mismatch
filter. Missing demographics do not become evidence of satisfying other criteria.

The existing cross-encoder reorders the top 10 or 20 hybrid/age-sex results, preserving
the remaining candidate order. It reads summary text in addition to the first-stage titles;
this confounds model changes with additional input evidence. Its 512-token limit and
192-token query cap, truncated spans and original rankings/scores are retained. No scores
from incompatible scales are added. TREC reranked files use monotonic rank surrogates;
raw learned logits remain separate in the saved ranking evidence.

## Results

Macro means across all 50 topics. nDCG uses linear TREC-grade gain; unjudged means zero
gain in this pooled benchmark, not established irrelevance. MRR is at depth 100.

| Configuration | nDCG@5 | nDCG@10 | MRR@100 | P@10 | Recall@100 |
|---|---:|---:|---:|---:|---:|
| BM25, no filter | 0.2082 | 0.1882 | 0.4443 | 0.2120 | 0.0972 |
| BM25, age/sex | 0.2363 | 0.2156 | 0.4870 | 0.2340 | 0.0979 |
| Dense, no filter | 0.3412 | 0.3138 | 0.5935 | 0.3660 | 0.1951 |
| Dense, age/sex | 0.3691 | 0.3471 | 0.6196 | 0.3800 | 0.1878 |
| Hybrid, no filter | 0.3595 | 0.3111 | 0.6098 | 0.3500 | 0.1726 |
| Hybrid, age/sex | 0.4090 | 0.3487 | 0.6778 | 0.3620 | 0.1677 |
| Hybrid, age/sex, rerank 10 | 0.4117 | 0.3446 | 0.6733 | 0.3620 | 0.1677 |
| Hybrid, age/sex, rerank 20 | 0.4276 | 0.3689 | 0.6456 | 0.3880 | 0.1677 |

The matched BM25 results reproduce the earlier title/condition baseline. Dense improves
over that matched lexical input. Hybrid barely changes nDCG@10 versus dense and lowers
Recall@100. Rerank-10 lowers nDCG@10; rerank-20 raises it while lowering MRR versus plain
hybrid. Reordering cannot recover candidates absent from the first-stage pool.

Exploratory paired-topic percentile bootstrap uses seed 0 and 10,000 resamples, with no
multiple-comparison adjustment:

| Versus dense + age/sex | nDCG@10 delta | 95% interval | Topic wins / losses / ties |
|---|---:|---|---|
| Hybrid + age/sex | +0.0016 | [-0.0474, +0.0511] | 22 / 22 / 6 |
| Hybrid + rerank 20 | +0.0218 | [-0.0173, +0.0616] | 27 / 17 / 6 |

Both intervals include zero. Neither supports a confident improvement claim. The biggest
rerank-20 gain against dense is topic 20 (+0.5327); the largest loss is topic 7 (-0.4652),
followed by topic 3 (-0.2172) and topic 25 (-0.1882). These are measured error-analysis
priorities, not permission to tune on the same cases. The older eligibility-text BM25
baseline achieved 0.3761 nDCG@10, above every configuration here; it uses different input
fields and remains documented in [experiment 0002](0002-bm25-baseline.md).

The prior bounded reranking result remains negative: dense 0.5584 versus reranked
0.5368/0.4956. Do not compare those scores directly with this much larger candidate universe
or erase the negative finding. Normal app search remains exact dense, legacy age/sex,
without reranking.

## Evidence and coverage

All final top-three results per topic (150 pairs) were reconstructed from hash/CRC-checked
original XML and passed through source-backed deterministic explanations and full-clause
screening. **150/150 remain insufficient information.** This is explanation coverage,
not screening accuracy. Broad clinical NLP, independent criterion labels and semantic
promotion remain unvalidated. No learned suggestion is promoted to an eligibility decision.

609/375,580 title inputs and 1/50 dense queries exceed the 256-token MiniLM limit. Raw
input identities and truncation rules remain recorded. Full-corpus criterion vectors and
full-corpus ANN were deliberately not introduced; the interactive app retains its separate
443-trial diagnostic plus three invented screening examples.

## Operational measurements

The sharded full index completed in 4,839.4 seconds (80.7 minutes) on this Windows CPU,
with four encoder threads and batch size 64. Length bucketing occurs only within immutable
4,096-document shards; saved vectors are restored to original document order. Interrupted
builds resume verified checkpoints without overwriting failed attempts. This elapsed time
includes other local work and is not a controlled throughput comparison.

The first full benchmark's single-pass median/p95 component times were:

| Component | Median | p95 |
|---|---:|---:|
| Full dense dot product | 22.04 ms | 36.62 ms |
| BM25 score lookup | 1.20 ms | 1.71 ms |
| Cross-encoder, 10 pairs | 592.56 ms | 712.42 ms |
| Cross-encoder, 20 pairs | 1,187.35 ms | 1,307.15 ms |

BM25 construction took 12.43 seconds. These kernel timings exclude query encoding,
filtering, sorting, persistence and UI/network overhead; they are not end-to-end API SLAs.

A separate isolated Qdrant rebuild reproduced all 443 vectors/payloads. Snapshot restore
and source rebuild both passed 100 exact-search checks each, alongside 100 on the original;
all 443 source texts were re-encoded with maximum absolute difference 8.94e-8 (limit 1e-6).
The source collection remained unchanged. HNSW efforts 10/32/128 were checked against exact
neighbors on the rebuilt diagnostic: mean neighbor recall at effort 32 was 0.996 unfiltered
and 0.992 with age/sex; effort 128 reached 1.0 for both. At effort 128, exact/ANN median
HTTP latency was 1.12/1.19 ms unfiltered and 1.39/1.44 ms filtered. There is no demonstrated
speed advantage on 443 points and no full-corpus ANN performance claim.

Current-registry acquisition was separately exercised against three public NCT IDs in an
explicit 2000-01-01 through 2026-09-11 window, one record per page. API identity was 2.0.5,
data timestamp 2026-09-11T09:00:04. Three records were added; replay yielded zero added,
zero changed and three unchanged. Mocked failure tests cover malformed/duplicate records,
cursor loops, interruption/resume, page budgets, altered acquisition settings, version
changes, gaps and older updates. The app catalog and TREC evidence were not modified.

## Identity and reproduction

A fresh Python 3.12 research environment installed from the observed constraints and a
Git-visible source export reproduced all eight metrics tables, all eight run files,
rankings, branch evidence, per-topic results and 150 explanations identically. It reused
checksum-verified existing model snapshots, full index and source archives; this was fresh
query inference, BM25 construction, reranking and explanations, not a second full document
encoding or a new network download. All eight saved runs were independently rescored and
400 method/topic orderings checked, including score-sorting the reranked prefix/tail.

Engineering verification passed 414 backend tests with actual PostgreSQL, Qdrant and local
models; 51 frontend tests; the production build; four Chrome workflows (two actual-service
workflows); and a separate recorded walkthrough. The lighter public-only clean environment
passed 385 tests with 15 explicit optional/integration skips. Tests in the final exported
source with the full research dependencies passed 387 tests
with 13 infrastructure/model opt-in skips. A clean `npm ci` in that export reported zero
audit vulnerabilities and passed all 51 frontend tests, formatting and build. Ruff
lint/format, Python compilation, dependency consistency and workflow/Compose YAML parsing passed. Docker is
not installed on this host, so Compose engine validation and the hosted Linux workflow
remain checks to run on GitHub after the user's manual push. Eight existing backend
deprecation warnings remain; they do not affect the measured results.

Actual dependency outages produced fixed readiness HTTP 503 responses while liveness
remained HTTP 200. Qdrant and project PostgreSQL restart cycles preserved the exact saved
operation ID and result; an API restart preserved them too. Active vector counts stayed
443/443/139. The independent PubMedBERT index passed three query and eight self-retrieval
checks, confirming a separate model boundary without changing the default model. Five
synthetic/public screenshots and a video are generated by the opt-in browser test; they
stay local rather than being published automatically.

Use the [release operating guide](../research-release.md) for environment, preparation,
benchmark, ingestion, migration, failure recovery and recording commands. The design is
recorded in [ADR 0015](../architecture/decisions/0015-reproducible-local-research-release.md).
Observed dependencies are in `requirements/observed-python312.txt`; frontend uses its lockfile.

| Artifact | SHA256 or pinned revision |
|---|---|
| Frozen rendered documents | `a7b133735968d60aa9562bdb8bf8a918345ce7302b12d66393f974cfe80dd84e` |
| Official 2022 topics | `c5d37709ba14f6cb341b0bea35a7f43bd1cf93647f939659667975229a7abe91` |
| Official 2022 qrels | `e569a531489e03f7b1fab03fe169c8ea66f4a59e8180fa9858b1a6e4bdcb0c5c` |
| Full index manifest | `7a589a5400cf279ae876c9bde11778aed7d4801d5c1d736291244353106e5bff` |
| Experiment packet | `6473dfa9555e5539aaf2994fa08440e2fa90f6f0d718cbe0c09eec688ed48e44` |
| all-MiniLM-L6-v2 revision | `1110a243fdf4706b3f48f1d95db1a4f5529b4d41` |
| ms-marco-MiniLM-L6-v2 revision | `233902d25c440f23af6f7d6e94d2946bac0bee0a` |

The benchmark packet includes per-file code hashes, complete model/runtime identities,
file inventories and all metrics/evidence. A Git-visible source export separately records
the base commit and actual working-byte inventory, including uncommitted work. No assistant
commit, push or release tag is created. Data/model/source checksums identify observed bytes;
they are not publisher signatures. External source/model licenses remain separate from the
code's MIT license. Generated evidence, raw data, model files, recordings and private local
tracking remain ignored. Public-facing docs contain aggregate results and reproducible
commands, not local credentials or patient data.
