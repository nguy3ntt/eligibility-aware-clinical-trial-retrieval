# 0018 — Expand two bounded screening rule families

Date: 2026-10-19. Status: accepted for the requested screening-coverage extension.

## Context

The frozen 2022 release explains 150 case/trial pairs but every one remains insufficient
information. Reproducing the saved assessments with the original implementation yields
1,434 unknown criterion outcomes: 1,213 shared/nested-context abstentions, 110 unknown
section/preamble abstentions and 111 unsupported whole predicates. This is missing
coverage, not evidence of incorrect eligibility or a reason to relax context guards.

## Decision

Preserve the original source export and all original assessments before changes. Add
`evaluation.screening_coverage` to capture, compare and verify paired coverage on the
same complete case/source/criterion identities. Hash-check the original release packet,
validate the synthetic cases against the official topic file and reproduce the entire
baseline before saving it. New comparisons never treat a supported outcome as an
independently validated correct label. Every changed decision retains its full source,
cited facts and before/after outcome. Reports use fresh destinations.

Implement only these extensions:

- **Whole-clause age predicates:** labelled ranges with explicit open/closed bounds,
  explicit paired comparisons, labelled `or older/younger` and `and older/younger`, and
  comparisons with an explicit `of age`/`old` suffix. Preserve age units and require a
  reliable, exact, current patient age in the same unit. Bare durations such as
  `>18 years` are deliberately unsupported. Extra disease, visit or timing text stops
  whole-clause recognition. An open upper bound excludes equality at that bound.
- **Platelet facts:** extend the existing measurement extractor with platelet labels
  and exact `/mm3`, `/mm³`, `x10^9/L` units. Canonicalize only spelling variants, never
  rescale numbers. Use the existing trial numeric parser and whole-clause comparison.
  Missing, conflicting, negative, conditional, historical, family/other-person,
  approximate and unsupported-unit evidence remains unknown.

The verifier becomes `bounded-screening-rules-v2`; patient vocabulary becomes
`synthetic-facts-rules-v2`. The verifier fingerprint includes both its dispatch code and
the new age grammar. The existing parser, source schema and stored criterion IDs remain
unchanged. Some recognized age phrases still have conservative parser review tags;
the verifier reads their complete retained source span with its separately versioned
grammar. It does not interpret a partial numeric span as an entire criterion.

Keep all existing unknown-preamble, shared-exception, cross-section-alternative and
nested-group guards. Only a **fully recognized age clause** can shield its own
`or older/younger` wording from the global alternative detector. Every other clause
and all ancestor context remain visible to that detector. Compute that shared-context
scan once per trial. Explicit comparisons do not become learned decisions.

Keep the frozen 34-pair/41-criterion fixture unchanged. Add a separate 31-pair,
35-criterion invented development fixture plus boundary/adversarial tests. These
authored contracts are not independent clinical labels. Do not select rules or thresholds
to maximize the historical count of supported decisions.

## Consequences

The normal CLI/API screening path uses v2 after restart. Code identity yields new
operation IDs; old saved results remain explicitly historical replay. No catalog import,
parser/index rebuild, vector update, model change, retrieval-default change or NLI
promotion is required. The existing web evidence view consumes the same response schema.

The immutable independent retrieval study remains a historical result of its frozen
source. Its strict live-code verification rejects this newer implementation as designed;
use the preserved original source/runtime for that historical verification. Never rerun
or tune the consumed 2021 cases and describe them as another unseen holdout.

Coverage is reported separately from accuracy. Independent criterion labels, clinical
validation and safe interpretation of complex eligibility language remain unmet. Read
the paired audit and reviewed experiment before claiming any practical improvement.
