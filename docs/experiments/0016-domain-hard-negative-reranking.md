# Retrospective domain hard-negative relevance-head experiment

Date: 2026-10-23. [Method and manual checks](../domain-hard-negatives.md).
[ADR 0022](../architecture/decisions/0022-domain-hard-negative-relevance-head.md).

## Question and frozen scope

Can judged, domain-confusable negatives improve the original relevance reranker beyond
a matched random-negative control? The fixed experiment adapts only 384 classifier
weights of `cross-encoder/ms-marco-MiniLM-L6-v2`, revision
`233902d25c440f23af6f7d6e94d2946bac0bee0a`. BERT and the original bias stay frozen.
It uses the existing query/summary pair template (query cap 192, pair cap 512 tokens),
source spans and original pinned model. This is not full-backbone fine-tuning.

Source: the already inspected 443 judgment-selected public trials, 50 synthetic TREC
2022 topics and 1,511 pooled labels. No original independent 2021 holdout is reused.
The separate original full-corpus benchmark is untouched. Working base commit:
`8521f5c32d0087a9c2154817ae5b02937b27393b`, with uncommitted extension source.
Ignored source export `artifacts/domain-hard-negative-source-v1` records working bytes;
all data/model/study manifests bind hashes, fixed parameters and runtime identities.

## Splits and training data

Case and trial lexical connected-component groups are hashed independently into fixed
60/20/20 partitions. Case near-duplicate threshold: word-five Jaccard 0.8. Trial threshold:
0.85 with at least ten shingles; exact normalized official-or-brief title plus conditions
also groups trials. Actual data yielded 50 singleton case groups and 443 singleton trial
groups. This provides a reproducible lexical proxy only; semantic and protocol-family
independence remain unproven.

| Partition | Synthetic cases | Trials | Same-partition judgments |
|---|---:|---:|---:|
| Train | 28 | 265 | 559 |
| Development | 14 | 89 | 46 |
| Test | 8 | 89 | 68 |

The remaining 838 cross-partition judgments are excluded. One training case has no
usable pair and is explicitly recorded as skipped. Training uses 182 pairs per sampler
across 27 cases, with identical positives and pair budgets for hard and seeded random
negatives. Positive pair occurrences: 94 grade one and 88 grade two. Grade one means
relevant-but-excluded and is never a relevance negative. Negatives are externally judged
grade zero only; unjudged candidates and screening decisions never become labels.

Hard negatives come from training-only BM25/dense top-50 lists, ordered by equal RRF60,
with source-condition word overlap or dense rank at most 20. Of 182 pair occurrences,
120 satisfy the recorded condition-overlap reason and 62 the high-dense-rank reason.
Each case uses at most four positives (at most two per grade) and two negatives. Random
negatives use the same judged-zero pool and can overlap hard examples; they are not
artificially made easy. Repeated endpoints across pairs are expected and retained.

## Fit, selection and chronology

Frozen evaluation-mode classifier-input vectors must reconstruct original logits within
absolute `1e-5`. Training uses CPU full-batch Adam, seed zero, 20 updates, learning rate
0.001, query-balanced pairwise softplus and a 0.01 squared weight-delta penalty.
Only checkpoints 0/5/10/15/20 are considered. Development nDCG@10 selects the checkpoint;
ties retain the earliest epoch. Hyperparameters and partitions were not retuned.

Both samplers had development nDCG@10 **0.4553758359 at every checkpoint** and therefore
selected **epoch zero**. Hard-negative pair loss fell from **0.7805 to 0.6505** (values
before updates 1/20); random-negative loss fell from **0.4835 to 0.4771**. Final weight
delta norms were 0.3670 and 0.1319 respectively. Final trained weights and histories
are preserved even though they were not selected. A falling training loss is not a
ranking improvement.

The original fit took 28.40 seconds including frozen feature extraction. Model,
training controls, features and protocol were sealed before opening the test stage.
The fitting loader hashes but does not deserialize test-case/label/candidate files;
source label validation parses grades for train/development endpoints only. Test data
cannot choose a checkpoint. The experiment is still retrospective because these public
cases were already used elsewhere in project development.

## Fixed test results

All eight cases remain in macro averages, including two without a judged relevant trial
in the disjoint trial partition. Reordering a prefix cannot increase candidate recall.

| Method | nDCG@10 | Recall@100 |
|---|---:|---:|
| Dense candidates | 0.3888 | 0.6042 |
| Original reranker, depth 20 | 0.4187 | 0.6042 |
| Random-negative head, selected epoch 0 | 0.4187 | 0.6042 |
| Hard-negative head, selected epoch 0 | 0.4187 | 0.6042 |

Hard versus original/random has zero delta because selection retained the original
weights. Its zero interval is a consequence of identical selected checkpoints, not
evidence of generalization. Hard versus dense nDCG@10 difference is +0.0299 with
exploratory paired bootstrap 95% interval **[-0.0473, +0.1449]** (10,000 resamples,
seed zero, no multiplicity correction). It includes zero and provides no demonstrated
benefit. These numbers must not be compared directly with earlier experiments using
different candidate populations and case sets.

## Artifacts and verification

Ignored immutable local artifacts:

- `data/processed/domain-hard-negatives-v1`: protocol, groups/split, mined pairs, explicit
  skip records, separate cohort labels/candidates and complete SHA256 inventories.
- `models/domain-hard-reranker-v1`: selected head, training summary, original model and
  corpus identities, case exposure and `promoted: false`.
- `evaluation/reports/domain-hard-reranker-v1`: sealed fit features, source-input spans,
  controls including unselected final weights, test chronology, rankings and intervals.

`python -m evaluation.domain_hard_negatives` reproduced both training histories,
checkpoint choices, 32 test rankings (four methods times eight cases), all metrics and
intervals identically from sealed features. Real-model checks confirm frozen parameters
and reconstructed logits. Browser/API tests check explicit opt-in, model/source identity,
historical replay, missing-artifact rejection and unchanged ordinary defaults. The
operating guide gives the complete manual procedure.

Final regression checks: 656 Python tests with all prepared service/model opt-ins,
67 frontend tests, nine Chrome workflows (six actual-service; recording opt-in skipped),
24 HTTP smoke checks, lint, formatting, production build and compilation passed.
All 232 local Markdown links resolve. The first combined HTTP/browser run correctly
encountered the API's single-operation 429 guard; running these checks sequentially
passed without relaxing that guard. Private planning, credentials, data, weights and
generated reports remain ignored; no staging, commit or push was performed.

## Interpretation

Implementation, actual training and evaluation are complete. **No learned ranking gain
or model promotion is earned.** The browser explicitly discloses the epoch-zero result.
No default, original model/index/catalog, independent historical result, screening rule,
clinical assessment or deployment is changed. This is useful infrastructure for honest
future experiments, with a preserved negative result. Stronger adaptation or independent
curation needs a new scoped experiment, not retrospective tuning of this small pool.
