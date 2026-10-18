# Independent retrieval evaluation on external TREC 2021 judgments

Date: 2026-10-18. Protocol: `independent-trec2021-v1`.
Study: ignored `evaluation/reports/independent-trec2021-v2`.
Decision: [ADR 0017](../architecture/decisions/0017-independent-trec2021-evaluation.md).
Commands and manual checks: [independent evaluation guide](../independent-evaluation.md).

## Question and independence

Does the existing exact dense configuration improve over matched title/condition BM25
on synthetic cases outside this project's recorded 2022 development set? That is the
single prespecified primary nDCG@10 comparison. Hybrid and fixed hybrid reranking
depths 10/20 versus dense are secondary exploratory contrasts.

The new test set consists of all **75 TREC 2021 synthetic cases**, with **35,832 external
judgments**, over the complete **375,580-trial April 27, 2021 corpus**. The official
[track description](https://www.trec-cds.org/2021.html) describes synthetic cases and
physician assessment; [NIST](https://trec.nist.gov/data/trials2021.html) supplies judgments
with grades 0 not relevant, 1 excluded, 2 eligible. These are historical source labels,
not newly established clinical eligibility.

Code/configuration, source URLs, runtime, corpus and model identities were frozen
before acquiring 2021 topics. The ranker never read qrels. All five systems' rankings
were sealed before the external labels were downloaded. No configurations or topic
subsets were changed after observing scores.

The case overlap gate passed for all 75 cases against all 50 development narratives.
Maximum normalized character 5-gram Jaccard was **0.1538** (2021 topic 40 versus 2022
topic 38), below the prespecified rejection threshold 0.8. Numeric topic IDs can overlap
across years and are not evidence of duplicate narratives. This lexical check cannot
prove semantic disjointness or absence from public model training data.

This is a **project-configuration holdout with external historical judgments**. It is
not externally registered preregistration or certified model-training independence.
After this run these cases have been inspected; tuning on them would consume the holdout.

## Frozen methods

All five methods retain legacy age/sex filtering, depth 100 and stable NCT-ID tie breaks.
BM25 and MiniLM receive the same title/condition representation. BM25 is Lucene with
k1=1.2, b=0.75 and the existing English tokenizer/stopwords. MiniLM uses 384-dimensional,
normalized float32 vectors and exact dot products. Each new query's full exact scores
matched an independent blocked computation within 1e-6 before ranking was accepted.

RRF uses equal branches, constant 60 and branch depth 100. The pinned cross-encoder
reorders only hybrid prefixes of 10/20, retaining original scores, ranks and input
truncation evidence. It receives summary text beyond the first-stage representation;
results are not a controlled comparison of models alone. Run files use rank-surrogate
scores to retain exact ordering; raw cosine/BM25/RRF/logit scales remain separate in JSON.

Use the existing pinned MiniLM revision `1110a243fdf4706b3f48f1d95db1a4f5529b4d41`
and cross-encoder revision `233902d25c440f23af6f7d6e94d2946bac0bee0a`.
All shard/render/model checks passed. The experiment reused verified existing corpus
and model artifacts; it did not rebuild the document embeddings.

## Results

Macro means over all 75 cases. Linear source grades determine nDCG; grades 1 and 2
both count as relevant for P@10, MRR and recall. MRR is truncated at 100. Pooled unjudged
trials contribute zero gain without being declared irrelevant.

| Configuration, all with age/sex | nDCG@5 | nDCG@10 | MRR@100 | P@10 | Recall@100 |
|---|---:|---:|---:|---:|---:|
| Matched title/condition BM25 | 0.2018 | 0.1959 | 0.3761 | 0.2547 | 0.1362 |
| Exact dense MiniLM | 0.3524 | 0.3277 | 0.6096 | 0.3920 | 0.1901 |
| RRF hybrid | 0.3808 | 0.3451 | 0.6582 | 0.4240 | 0.1814 |
| Hybrid + rerank 10 | 0.4054 | 0.3569 | 0.7120 | 0.4240 | 0.1814 |
| Hybrid + rerank 20 | 0.3988 | 0.3626 | 0.6707 | 0.4307 | 0.1814 |

Seed-0 paired-topic percentile bootstrap, 10,000 resamples:

| Contrast | Role | nDCG@10 delta | 95% interval | Wins / losses / ties |
|---|---|---:|---|---|
| Dense versus matched BM25 | Primary | +0.1319 | [+0.0647, +0.1995] | 43 / 25 / 7 |
| Hybrid versus dense | Exploratory secondary | +0.0173 | [-0.0152, +0.0495] | 40 / 28 / 7 |
| Hybrid rerank-10 versus dense | Exploratory secondary | +0.0292 | [-0.0077, +0.0643] | 41 / 27 / 7 |
| Hybrid rerank-20 versus dense | Exploratory secondary | +0.0349 | [-0.0031, +0.0688] | 42 / 25 / 8 |

**The prespecified primary comparison supports a dense advantage over this matched BM25
configuration on these cases.** All three secondary intervals include zero and have no
multiplicity adjustment. They do not establish a reliable hybrid/reranking advantage or
earn default promotion. Hybrid also lowers Recall@100 versus dense; reranking cannot
recover candidates absent from its first-stage pool. Ordinary search remains exact dense,
legacy age/sex and no reranking.

The earlier 2022 benchmark and its BM25 variants remain separate historical results.
Do not interpret differences between the 2021 and 2022 means as a software improvement:
the topic and judgment populations differ. The primary comparison here concerns only
matched title/condition BM25; it does not establish superiority over every lexical input.

## Coverage and failure analysis

Mean judged fraction of the top ten was **34.13% BM25, 48.93% dense, 54.27% hybrid,
54.27% rerank-10 and 55.60% rerank-20**. Much of the ranking output is unjudged, and
coverage differs by method. Pooled evaluation therefore has substantial missing-label
limitations. The 2021 cases also have **17/75 dense query truncations** at 256 tokens.
The full index retains the prior 609 document truncations.

Case-level counterexamples are retained rather than tuned away:

- **Topic 14:** dense nDCG@10 is 0.0000 versus BM25 0.4557. All ten dense results
  are unjudged; this proves zero observed gain, not that all ten are medically irrelevant.
  Hybrid scores 0.3991 and rerank-20 0.4515. BM25's top ten include seven source-grade-1
  and one grade-2 trial; this also illustrates relevance versus source eligibility grades.
- **Topic 55:** dense scores 0.9608 with nine grade-2 results in the top ten. Hybrid
  drops to 0.6422, rerank-10 to 0.3832 and rerank-20 to 0.1478. Rerank-20's top ten
  contain two grade-2, four grade-0 and four unjudged records. Higher average secondary
  scores conceal this large failure.
- **Topic 3:** dense 0.8062, hybrid 0.4007 and rerank-20 0.7569. Fusion can weaken
  a strong dense ranking even when a later reranker partially recovers it.
- Topics **25, 28, 34, 42, 53 and 65** have zero observed top-ten gain for every
  method. All 75 cases stay in the denominator. Dense has ten zero-gain cases; BM25
  29, hybrid/rerank-10 nine each and rerank-20 seven.

These are rank/judgment observations, not independent clinical interpretation of the
cases. No explanation or screening accuracy was measured in this retrieval extension.
The previous 150 original-XML screening explanations remain insufficient information.

## Audit identities and execution evidence

Git base commit: `5ea732c3f214cca44b7ecb8d5f4f61903efb9dcb`, with a dirty working tree.
The base commit alone does not identify the new implementation: the protocol contains
byte hashes of all 103 non-test Python implementation files and exact runtime/model
identities. Source export: ignored `artifacts/independent-evaluation-source-v1`.

| Record | Value |
|---|---|
| Final freeze, UTC | 2026-10-18T12:47:03.492325+00:00 |
| Ranking seal, UTC | 2026-10-18T12:51:23.242695+00:00 |
| Scoring, UTC | 2026-10-18T12:52:05.990759+00:00 |
| Protocol SHA256 | `1068c40eb15d0dc7025c21febd847dae8db7fd473ae2b028db21e7b2c1520fc1` |
| Ranking seal SHA256 | `e826dcc1b8fcf43b8777c4691691adc3e0afc230a3c376e38952e0dccb032566` |
| Qrels SHA256 | `ba7a2cddc90285e75cd76adcd483394a6c9bacf7017113222058ba6537e6d8ac` |
| Evaluation SHA256 | `22f69822ee79f8f4ecb7be539fe032d83488b926b19e748c8e914c6feb1c9853` |

The raw source metadata confirms freeze < ranking seal < qrels acquisition. The unused
first freeze in report folder `independent-trec2021-v1` preceded a formatting-only
correction and acquired no new topics or judgments. It remains preserved. The actual
study uses `independent-trec2021-v2`; no result-based refreeze occurred.

Verification passed: 23 new fixture tests; the full offline Python suite **424 passed,
13 opt-in tests skipped**; repository lint/format and compilation; the actual full-corpus
five-system run; source/seal checks; and **3,040 independent metric calculations plus
375 ranking-order comparisons** from the saved run files. The independent metric audit
uses a separate standard-library implementation rather than the production metric
functions. One existing Starlette/httpx deprecation warning remains. Service/model opt-in
tests were not all rerun; the new offline experiment itself used both actual local models.

## What remains unmet

Model-training contamination cannot be ruled out. Semantic overlap is not independently
reviewed. Bootstrap intervals describe these topic samples and pooled labels, not clinical
reliability. Local seals are operator-controlled evidence, not externally authenticated
registration. No independent criterion-level accuracy, real-patient use, clinical
validation, modern-registry generalization, deployment or model promotion is established.
The operator must reserve another untouched case set before further confirmatory tuning.
