# Source-linked missing-information review audit

Date: 2026-10-24. [Operating and manual guide](../missing-information-review.md).
[ADR 0023](../architecture/decisions/0023-source-linked-missing-information-review.md).

## Scope and method

The user requested prioritisation of missing information. This extension adds a
separate deterministic review artifact, without changing extraction, parsing,
verification, grouped logic, eligibility outcomes, retrieval defaults or model weights.
Only synthetic cases and original public trial evidence are used. Learned advisories
do not generate questions or influence the worklist.

Fact items require an explicit existing verifier gap on a recognised predicate. They
deduplicate by canonical name and requested unit. Ranking is lexicographic: distinct
trials without existing blockers, source-criterion count, trial count, then stable
fact/unit key. All counts and source references are saved. This is reuse prioritisation,
not expected information gain, medical urgency or a prediction of trial eligibility.

Unsupported wording and scope go to interpretation review. Grouped unknown leaves
below already-settled expressions remain in a separate retained list. Global unresolved
scope takes precedence over local missing-fact questions. Blockers never disappear.
The browser covers one selected pair; the service and audit can aggregate up to ten
different trials for exactly the same synthetic case/version.

## Inputs and provenance

The fixed source is the prior `screening-coverage-after-v2` audit: 150 original
historical case–trial pairs, 50 synthetic TREC 2022 cases and 1,434 criteria. No 2021
cases, retrieval judgments, model fitting, new clinical data or thresholds are used.
All original source evidence and prior studies remain unchanged.

The new fixture `evaluation/data/fixtures/missing_information_review.json` contains
21 wholly invented development contracts. It preserves all prior fixture files and
covers repeated gaps, conflicts, units, family evidence, unsupported wording,
unknown preambles, existing blockers, gates and grouped AND/OR/NOT/nested branches.
An unrecognised age phrasing deliberately stays an interpretation task; this extension
does not widen the verifier to force a fact question.

The study `evaluation/reports/missing-information-review-v1` records an immutable
protocol and code/schema/fixture fingerprints, a byte-identical copy of the original
assessments, both pair-level and three-trial-per-case plans, and authored results.
The ignored final working-source export is `artifacts/missing-information-review-source-v2`,
based on commit `8521f5c32d0087a9c2154817ae5b02937b27393b` plus uncommitted extensions.
Private planning, credentials, original data, weights and generated reports remain ignored.

## Results

All **21/21 authored contracts** pass. All **150/150 original assessments and statuses**
are reproduced without modification: 149 insufficient-information and one likely exclusion.
Original unknowns remain **1,429**; the worklist does not turn them into supported decisions.

| Review disposition | Ordinary pair plans | Grouped pair plans |
|---|---:|---:|
| Plans | 150 | 150 |
| Plans with active fact items | 1 | 1 |
| Deduplicated fact items | 1 | 1 |
| Active fact references | 2 | 2 |
| Interpretation references | 1,427 | 1,505 |
| Unknown references in settled branches | 0 | 4 |

The single active fact item concerns age in months for case 45/trial NCT00676351 and
links two existing checks. Aggregating
the three trials for each of the 50 cases retains the same single item in one case.
Most unknowns are still interpretation limitations, so broad fact-acquisition benefit
is not supported. Grouped references are terminal tree nodes (or flat criteria when
global scope is unresolved); counts are not directly comparable with flat criteria and
do not indicate worse/better accuracy. Existing assessments, blockers and full trees
remain available for interpretation.

The audit's `verify` command reproduced every plan, source quote, disposition, ordering
and aggregate metric identically from the sealed assessments. Plans are versioned by
implementation and source identity. Historical packets without plans stay historical;
no new review result is computed when opening them.

## Validation and interpretation

Tests cover duplicate facts, separate units, conflicting/family evidence, source
alignment, mixed-case/duplicate-trial rejection, incompatible grouped packets,
wrong counts/order/dispositions, altered inventories, historical compatibility and
incorrect requested units. Actual-service browser checks exercise a creatinine item,
saved replay, retained likely-exclusion blockers and grouped interpretation review.

Final checks: 691 Python tests with all prepared model/service opt-ins, 82 frontend
tests, ten Chrome workflows (seven actual-service; recorder opt-in skipped), 24 HTTP
checks, lint, formatting, production build and compilation passed. Both documented
CLI examples were executed. All 242 local Markdown links resolve. HTTP and browser
suites ran sequentially against the existing single-operation API guard.
An additional browser assertion initially used an offline-only historical trial outside
the interactive catalog. That invalid instruction/assertion was removed; the immutable
catalog was not expanded. The historical example remains in the audit and the invented
CLI example tests deduplication. The preliminary source snapshot is preserved locally.

The feature is an engineering and workflow extension, not an independently validated
ranking algorithm for clinical review. Review time saved, question utility, criterion
accuracy and clinical benefit are unmeasured. No retrieval or eligibility promotion,
deployment, staging, commit or push is performed. The earlier hard-negative experiment
and its negative result remain intact.
