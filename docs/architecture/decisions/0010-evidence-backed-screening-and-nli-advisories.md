# 0010 — Evidence-backed screening with separate NLI advisories

- Status: accepted
- Date: 2026-09-09

## Context

The existing synthetic profiles and trial parses preserve evidence but are bounded and sometimes compound. Their extracted numbers and type tags cannot safely be executed as complete predicates. Retrieval relevance is also separate from eligibility. We need explicit criterion outcomes, missing-information reports and measured semantic behavior without converting uncertain language into a clinical decision.

## Decision

Add a standalone research-screening service and CLI, preserving the current retrieval defaults and all earlier model/parser/index contracts. Re-extract the synthetic case and reparse trial evidence before verification; reject edited or incompatible derived values. Each assessment embeds the original profile and parsed trial, source identities, exact criterion evidence, relevant fact IDs, rule IDs and verifier fingerprint.

Deterministic rules accept only complete supported sex or numeric clauses. Numeric facts must be asserted, current, patient-specific, exact, consistent and in identical units. Do not convert age/month/calendar or laboratory units, infer a missing measurement, select among conflicting results, or execute a numeric substring while ignoring remaining wording. A supported inclusion predicate must be true; a supported exclusion predicate must be false. An explicit inline “For male/female participants:” condition can yield `not_applicable` only when reliable sex evidence demonstrates that the condition does not apply. Unsupported bodies remain unknown even when the gate could be false.

Unknown preambles, shared alternatives/conditions/exceptions and nested or embedded group context cause abstention. Cross-section exception cues conservatively block rule interpretation throughout the trial. This intentionally sacrifices coverage; it does not claim complete clinical-language understanding. The bounded source/context rules remain inspectable and require more independent labels before extension.

Aggregate supported violations as `likely_exclusion`; unresolved criteria or no applicable satisfied criteria produce `insufficient_information`. Only a complete set of supported satisfied/not-applicable outcomes with at least one satisfied criterion can produce `potential_match`. These are research screening labels requiring professional review, never confirmed eligibility or advice. Missing information is not satisfaction. Rules emit no fabricated probability.

Use the pinned, local discriminative [NLI cross-encoder](https://huggingface.co/cross-encoder/nli-deberta-v3-small/tree/fa2804872c3b4bd748f38c0185cc85775361e735) as a separate advisory experiment. It predicts contradiction/entailment/neutral text relations, not clinical eligibility. Full synthetic narrative and verbatim criterion form the ordered input pair. Reject pairs over 512 tokens rather than silently truncate evidence. Use only safetensors, no remote code, pinned files/hashes, CPU/evaluation mode and recorded runtime settings. Download weights only; never send case text to an external inference service.

Learned proposals are explicitly `learned_nli`, `promoted: false`, and never replace deterministic outcomes, unknowns, blocker lists or trial status. Unsupported shared context prevents even advisory inference. Raw softmax scores and the fixed 0.95 advisory threshold are marked nonclinical. Temperature scaling is evaluated separately on a disjoint authored calibration split; it is not silently installed into CLI inference.

## Evaluation and consequences

Freeze labelled fixtures before NLI scoring. Evaluate exact rule outcomes at criterion and multi-criterion trial levels. Report the original public-trial audit separately as unlabelled coverage. Evaluate NLI on separate calibration/test pairs, selecting temperature only by calibration NLL from a declared grid. Report accuracy, Brier score, NLL, reliability bins/ECE, high-confidence precision/coverage and a Wilson lower confidence bound. Zero selected predictions have undefined precision, not perfect precision. One-criterion shadow trial results are advisory diagnostics, not deployed screening results.

The first diagnostic did not justify semantic promotion: one high-confidence test decision was wrong; temperature scaling improved calibration-set NLL but worsened test NLL/ECE and removed all proposals at the fixed threshold. Keep the negative results, original threshold and frozen test set. Broader deterministic coverage and independently labelled semantic/domain validation remain necessary before dependable public-trial screening.

No search reranking, database schema, new service infrastructure, UI, cloud deployment or automatic LLM eligibility decision is introduced. Foundation-only rules work without ML dependencies. The optional `verification` dependency group enables local NLI. Detailed cases, predictions, model files, calibration results and milestone tracking stay ignored; publish only reusable code, tiny invented fixtures and reviewed methods/results.
