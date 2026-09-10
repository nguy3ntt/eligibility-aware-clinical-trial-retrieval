# Bounded research screening and semantic verification

Date: 2026-09-09. This is a local working-tree experiment, not a release commit or clinical validation. The engineering workflow is complete for bounded deterministic rules and non-promoted semantic advisories. Dependable public-trial screening and semantic promotion are **not** established. See [ADR 0010](../architecture/decisions/0010-evidence-backed-screening-and-nli-advisories.md) and the [manual guide](../eligibility-verification.md).

## Questions and protocol

1. Can supported complete trial requirements be checked against synthetic evidence without treating missing information as satisfaction?
2. Can unsupported context, conflicting measurements and provenance tampering cause explicit abstention or rejection?
3. How accurate and well-calibrated is a pinned general NLI model on separately authored synthetic text-relation pairs?

The deterministic fixture contains 34 invented patient–trial pairs and 41 expected criterion outcomes, including multi-criterion trial summaries. Labels were authored before running the verifier. A separate fixture contains 24 calibration and 30 disjoint test NLI pairs, frozen before model inference. Test labels do not choose the model, threshold, temperature or sample. These are authored development/disjoint synthetic splits, not independent clinical annotation or held-out real-world validation.

The historical audit crosses all 16 existing synthetic profile fixtures with the 12 original public trial parses: 192 pairs and 2,224 criterion assessments. It does not use qrels to claim eligibility accuracy, alter the judged retrieval pool or update any stored index.

## Deterministic verification

Rules accept complete supported sex/numeric predicates with exact current patient facts and identical units. Full profiles and trial parses are revalidated and reproduced. Unknown preambles, unresolved nested groups and shared alternatives/exceptions prevent interpreting extracted fragments independently. Supported inclusion predicates must hold; supported exclusion predicates must not hold. Explicit inline sex applicability can produce `not_applicable`; missing sex cannot.

| Development check | Result |
|---|---|
| Exact patient–trial pairs | 34/34 |
| Exact criterion outcomes | 41/41 |
| Outcome distribution | 12 satisfied, 9 violated, 19 unknown, 1 not applicable |
| Supported decision coverage | 22/41 = 53.66% |
| Supported decision precision | 22/22 = 100% on authored contracts |
| Historical trial audit | 192/192 insufficient information |
| Historical criterion audit | 2,224/2,224 unknown |

The historical audit reveals a substantial coverage gap. Its criteria include unsupported sections, compound predicates, nested context and indirect quantities. All-unknown output is an honest abstention result, not proof of correctness, medical incompatibility or eligibility. The small authored rule fixture does not justify a general clinical accuracy claim. Rules emit no probability and therefore have no fabricated confidence-calibration score.

## Semantic model and calibration

The local discriminative model is [cross-encoder/nli-deberta-v3-small](https://huggingface.co/cross-encoder/nli-deberta-v3-small/tree/fa2804872c3b4bd748f38c0185cc85775361e735), revision `fa2804872c3b4bd748f38c0185cc85775361e735`, Apache-2.0. Its model card describes general SNLI/MultiNLI training, not clinical eligibility training. Fixed label order is contradiction, entailment, neutral.

Inference uses full synthetic narrative followed by verbatim criterion, CPU, four threads, seed 0, evaluation/inference mode, local safetensors and no remote code. Pairs above 512 tokens abstain instead of being truncated. Exact file hashes, snapshot identity, tokenizer/model settings and package versions are recorded. No synthetic case text is uploaded; only model files were downloaded.

The advisory threshold is fixed at 0.95. Temperature selection minimizes calibration-set NLL over `[0.5, 0.75, 1, 1.5, 2, 3, 5]`; the selected temperature is **3.0**. It is an evaluated calibration experiment, not an automatically activated CLI setting. Normal CLI advisories retain raw softmax probabilities with an explicit nonclinical warning.

| Test metric, 30 pairs | Raw probabilities | Temperature 3.0 |
|---|---:|---:|
| NLI accuracy | 24/30 = 80% | 24/30 = 80% |
| Negative log likelihood | 0.406480 | 0.446535 |
| Multiclass Brier score | 0.241273 | 0.228970 |
| Expected calibration error, 10 bins | 0.116007 | 0.165547 |
| High-confidence non-neutral decisions | 20/30 | 0/30 |
| High-confidence precision | 19/20 = 95% | Undefined; no decisions |
| 95% Wilson precision lower bound | 0.763864 | Undefined |
| One-criterion shadow trial outcome accuracy | 27/30 = 90% | 9/30 = 30% |

The shadow trial diagnostic maps a single labelled text relation and section into a proposed outcome; it is not an evaluation of complete historical trials or deployed screening. The scaled shadow result reflects abstention on every pair, matching only neutral gold cases.

Calibration-set NLL improved from 0.933978 to 0.559502. This did **not** translate into better test NLL or ECE, although test Brier improved. The raw model made a high-confidence error on an invented family-history example: it treated the father's hypertension as support for the patient's hypertension. Other test errors involved future medication, missing causal diagnosis, numeric thresholds, uncertainty and family experiencer. These failures are retained, not removed from the dataset.

**Semantic promotion remains disabled.** The 19/20 raw precision estimate has a wide interval; calibration removes all decisions at the original threshold, and clinical/domain validation is absent. `learned_nli` proposals always have `promoted: false`; they cannot change deterministic outcomes, unknowns, blockers or trial status. No threshold was relaxed to manufacture coverage or superiority.

## Engineering checks

The final full suite contains 313 local tests, with 299 publishable tests and 14 pre-existing ignored local milestone tests. Checks include all prior retrieval/parsing tests, five isolated live database tests and a real pinned-NLI test. New coverage includes whole-clause boundaries, unsupported/shared context, malformed units, missing/conflicting/family/historical evidence, open/closed numeric bounds, source and saved-output tampering, protected report paths, foundation-only operation, split contamination, independent calibration arithmetic, neutral/low-confidence abstention, advisory non-promotion, model checksums, Windows long download paths, replay and token-limit rejection.

The first full run found that the existing local Qdrant service was stopped: all five database tests failed to connect while the other 307 tests passed. Starting the existing service resolved this environment issue. No infrastructure definition was changed. Upstream Starlette/httpx and DeBERTa/PyTorch JIT deprecation warnings remain visible; they are not test failures.

Manual commands exercise supported match, blocker, missing measurement, not-applicable condition, advisory-only semantics, and the existing synthetic-profile/public-trial path. Final source-derived reports, predictions and metrics replay deterministically on the recorded environment. Existing `trials_v1` and `trials_hybrid_v1` remain at 443 points and `criteria_v1` at 139; their verified source/vector contracts and retrieval defaults are unchanged. No commit or push was made.

## Evidence and remaining work

Final local reports are `evaluation/reports/m8-screening-release-v2/`, `m8-screening-replay/`, `m8-nli-release-v2/`, `m8-nli-replay/`, and `m8-manual-final.json`. Manifests include code/fixture/model hashes, exact outcomes, reliability bins, original predictions and limitations. Earlier diagnostics remain local. All generated reports, model weights, source/derived data, agent instructions and milestone tracking are Git-ignored; only reusable implementation, tiny invented fixtures and reviewed methods/results are publishable.

This result completes bounded engineering and evaluation, not the broader goal of dependable clinical-language screening. Wider whole-criterion rule coverage, independent synthetic/domain labels, more robust semantic modelling/calibration and full-corpus validation are still needed. Future reranking/explanations may reuse the evidence contracts, but must not promote these advisories or equate relevance, absence of contradiction and confirmed eligibility.
