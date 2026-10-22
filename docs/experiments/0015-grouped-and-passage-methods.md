# Grouped logic and field/passage development diagnostics

Date: 2026-10-22. Decisions: [0020](../architecture/decisions/0020-opt-in-grouped-screening.md)
and [0021](../architecture/decisions/0021-bounded-field-passage-retrieval.md).
Commands and manual procedures: [methods guide](../grouped-and-passage-methods.md).

## Scope and source identity

These requested extensions add opt-in research methods, not default promotion or clinical
validation. All patient cases are synthetic; trial evidence is the original public XML.
The ordinary v1 parser, v2 verifier, active 443/443/139 indexes, catalog and pinned models
are preserved. The prior full-corpus and independent studies remain historical and are
not overwritten. The 2021 cases are not reused as a fresh holdout.
The working base commit is `20a051a0b7d3049a586ace89695e68c53ad3cda9`, with uncommitted
extension files. An ignored Git-visible source export at `artifacts/method-extensions-source-v1`
records the complete working-byte inventory and dirty base identity without staging.

Each generated study records source/model/configuration/implementation hashes. Retrieval
uses final artifact `data/processed/field-passages-v2`; its format is `field-passages-v1`.
It contains 13,058,564 bytes of declared vector/segment files, excluding the manifest,
models and existing sources. Preparation reused local models and took about 108 seconds.
The preliminary artifact and intermediate grouped report remain ignored and inspectable.
Final local reports are `evaluation/reports/grouped-method-v3` and
`evaluation/reports/passage-method-v2`. A fresh retrieval rerun reproduced all six
methods' aggregate metrics and paired comparison intervals identically.

## Grouped screening

Thirty authored development cases cover AND/OR, nested lists, NOT, conditionals, explicit
waivers/exceptions, unknown facts, mismatched units, family evidence and ambiguous scope.
All 30 expected trial statuses match. Independent possible-world enumeration checks
three-valued truth tables; separate tests cover source alignment, tampered packets,
depth limits, malformed empty operands and preservation of unrelated age blockers.
These tests are engineering contracts; no independent human review or criterion accuracy
measurement has been performed.

The paired historical audit retains all 150 original pairs and 1,434 original criteria.
Grouped conclusions remain **149 insufficient-information, one likely exclusion and
zero potential matches**, matching the ordinary v2 trial summaries. Ninety-four pairs
require global scope review. The tree exposes local predicates without treating them as
independent blockers or proof of satisfying the complete trial. No broad coverage gain
is claimed. An early stricter candidate unnecessarily masked an age blocker because of
balanced descriptive parentheses; the final rule and its regression test preserve it.

## Controlled retrieval comparison

Same 443 judgment-selected trials, all 50 inspected 2022 topics, 1,511 pooled judgments,
legacy age/sex filtering and depth 100. MiniLM model/revision/query text are unchanged.
BM25 title and summary baselines are saved before dense comparisons. All methods use
the same pooled labels; unjudged trials have zero metric gain, not verified irrelevance.
These scores cannot be compared directly with the separate full-corpus study.

| Method | nDCG@10 | Recall@100 |
|---|---:|---:|
| BM25 title/conditions | 0.3823 | 0.6852 |
| BM25 summary | 0.3430 | 0.7051 |
| Unchanged exact dense baseline | **0.5584** | 0.7518 |
| Dense single summary | 0.5795 | 0.7551 |
| Separate fields, RRF | 0.3871 | 0.7556 |
| Separate passages, RRF | **0.3805** | **0.7606** |

Exploratory paired-topic percentile bootstrap, seed 0, 10,000 resamples, nDCG@10
differences versus the unchanged dense baseline:

| Candidate | Mean delta | 95% interval |
|---|---:|---|
| Single summary | +0.0211 | [-0.0104, +0.0535] |
| Separate fields | -0.1713 | [-0.2280, -0.1152] |
| Separate passages | -0.1779 | [-0.2326, -0.1243] |

No multiplicity correction or unseen-case inference is claimed. Passage fusion raises
pooled candidate recall by about 0.009 absolute but substantially worsens top-ten quality.
Single-summary improvement is uncertain. **No method is promoted and no parameters were
retuned after viewing these results.** Broader, noisier fields and equal RRF contributions
are plausible causes of poorer top ranks, not established causal findings.

## Capacity, timing and evidence

Single-summary controls: 443 inputs, 311 truncated. Whole-field controls: 1,439 inputs,
263 truncated. Passage inputs: 2,469, zero truncated. Patient-query truncation remains
explicit and identical across dense comparisons. Within each field, multiple passages
contribute at most once per trial. Evidence records the winning original XML text item,
source SHA256, character/token spans, raw cosine, branch rank and fusion contribution.

Observed median/p95 warm ranking-only CPU time was about 1.13/1.50 ms for baseline and
3.30/3.90 ms for passages. These timings exclude model/query encoding, loading and all
API/database/browser overhead. They are a single-machine diagnostic, not service latency
or a scalability claim. Full-corpus passage retrieval was not built or evaluated.

The browser exposes experimental grouped screening separately from the unchanged
ordinary assessment and offers passage retrieval only in the laboratory. Replay remains
explicitly historical, and passage source identity participates in operation IDs.
The app checks the explicit dense-source/hybrid-catalog relationship rather than
mistaking their different schema versions for incompatible evidence.

The operating guide lists tests and source files. Local generated reports, models,
artifacts, agent instructions and milestone tracking remain Git-ignored. No deployment,
staging, commits or pushes are part of this work.

## Engineering verification

All **619 Python tests** passed with actual PostgreSQL, Qdrant, reranker and NLI
integrations enabled, including 84 new method tests. All **64 frontend tests** passed;
build/type, formatting, Python lint and compilation checks passed. Chrome passed
**eight workflows**, including five using actual local services; only the optional
video recorder was skipped. The new workflow checked grouped source evidence,
passage disclosures, stored replay and unchanged ordinary defaults. Existing upstream
FastAPI/HTTPX and Torch deprecation warnings remain; no dependencies were changed.
The final HTTP smoke suite also passed all 24 checks. All 103 checked local document
links resolved, and Git whitespace checks passed. Generated evidence and private tracking
remain ignored; the assistant did not stage, commit or push.
