# Bounded age and platelet screening coverage

Date: 2026-10-19. Decision: [ADR 0018](../architecture/decisions/0018-bounded-screening-coverage.md).
Manual checks: [screening coverage guide](../screening-coverage.md).

## Question and scope

Why did all 150 historical case/trial pairs in the full 2022 release remain insufficient
information, and can a carefully bounded deterministic extension recover useful evidence?
The audit covers the same 150 previously inspected pairs, all 50 synthetic cases and
all 1,434 original criteria. It is development coverage analysis, not a new held-out
evaluation or an independent accuracy measurement.

The baseline first reproduced every original stored assessment, case and trial parse,
using the original rule implementation and a checksummed release explanation packet.
It was preserved in `evaluation/reports/screening-coverage-before-v1`; original source
was exported to `artifacts/screening-coverage-before-v1`. The original release, frozen
fixtures, corpus, models and indexes were not overwritten.

The new rules recognize whole age expressions with explicit open/closed bounds and
same-unit platelet facts. They keep global context safeguards and abstain on missing,
unsupported or conflicting evidence. Verifier version is `bounded-screening-rules-v2`;
patient vocabulary version is `synthetic-facts-rules-v2`. The parser and criterion IDs
are unchanged. The verifier's complete age grammar can recognize a clause even when
the original parser retains review tags; the browser explains this and retains those tags.

## Baseline diagnosis

| Reason | Original unknown criterion assessments |
|---|---:|
| Shared or nested context requires review | 1,213 |
| Unknown section or preamble | 110 |
| Unsupported or incomplete whole predicate | 111 |
| Total | **1,434** |

The dominant limits are complex context and unsupported clinical language, not a
threshold that can safely be reduced. Bare condition labels, diagnosis qualifiers,
treatment histories, consent, visit timing and complicated alternatives remain outside
this extension. No NLI suggestion is promoted to a deterministic decision.

## Paired historical coverage

Final candidate report: `evaluation/reports/screening-coverage-after-v2`.

| Measure | Before | After |
|---|---:|---:|
| Pairs | 150 | 150 |
| Criteria | 1,434 | 1,434 |
| Unknown criteria | 1,434 | 1,429 |
| Satisfied criteria | 0 | 4 |
| Violated criteria | 0 | 1 |
| Supported criterion fraction | 0% | 0.35% |
| Insufficient-information pairs | 150 | 149 |
| Likely-exclusion pairs | 0 | 1 |
| Potential-match pairs | 0 | 0 |

All five transitions retain explicit same-unit patient age evidence:

| Synthetic topic | Trial | Complete criterion | Cited age | Outcome |
|---|---|---|---|---|
| 2022:7 | NCT00458263 | Ages 3 to <9 years | 3 years | satisfied |
| 2022:16 | NCT02115854 | adults above 18 years, | 39 years | satisfied |
| 2022:42 | NCT00458263 | Ages 3 to <9 years | 9 years | violated |
| 2022:50 | NCT02664584 | >60 years of age | 70 years | satisfied inclusion |
| 2022:50 | NCT02664584 | <60 years of age | 70 years | satisfied exclusion predicate is false |

The case aged exactly 9 violates the open upper bound and becomes a **likely exclusion**.
Other unresolved criteria stay present. Satisfying the age requirements in the other
pairs does not establish a potential match or full eligibility.

Shared/nested abstentions remain **1,213**, and unknown-section/preamble abstentions
remain **110**. Unsupported whole-predicate outcomes fall from 111 to 104; two newly
recognized age clauses still abstain because patient and criterion age units differ.
There is no calendar conversion. The historical set contains no newly supported
platelet comparisons. Platelet behavior is demonstrated on authored contracts only.

This is a modest measured gain. The five source-backed rule applications have not been
independently labelled for clinical correctness. Fewer unknowns alone are not accuracy.

## Authored regression and failure checks

The frozen original fixture remains **34/34 exact pairs, 41 criteria**, including its
19 required unknowns. A separate invented fixture adds **31/31 exact pairs, 35 criteria**:
9 satisfied, 7 violated and 19 deliberately unknown. The labels are authored development
contracts; their exact-match accuracy of 1.0 is not a clinical performance estimate.

New boundary and adversarial checks cover:

- inclusive/exclusive lower and upper bounds, equality at the cutoff, paired bounds,
  explicit age suffixes and months without conversion;
- whole-clause recognition, rejecting added diagnosis, visit, timing and exception text;
- preserving cross-section exceptions, unrelated alternatives and nested-group abstention;
- platelet boundary comparisons, exclusion inversion, spelling normalization and unit mismatch;
- missing, negative, approximate, conflicting, historical, planned, family/other-person,
  conditional and invalid-rate measurements;
- case/source alignment, report tampering, reproducible decisions and fresh-output protection.

A final safety pass also rejects repeated terminal punctuation on new age expressions
through the complete verifier, rather than testing the grammar alone. Intermediate
candidate/fixture reports ending in `v1` remain preserved. Final reports use `v2`;
the five historical outcome transitions are the same in both candidates.

## Integration and verification

- **509 Python tests passed**, including actual PostgreSQL, Qdrant, NLI, reranker and
  full API integration. The new coverage test module contributes 72 cases.
- **24 real HTTP checks passed** after restarting the API with final source.
- A fresh real API request screened synthetic case 2022:29 against NCT00258570,
  returned verifier v2 and two supported age checks, and retained the trial's
  insufficient-information status. The packet is stored under ignored artifacts.
- **59 frontend tests**, production build/type checks and formatting passed.
- **Seven Chrome workflows passed**, including four actual-service workflows and a
  new age-evidence/source-fact check. The opt-in demo recorder was skipped. After the
  final evidence-note clarification, the new browser workflow passed again.
- Python lint, formatting, compilation, paired-report checksum/reproduction checks
  and source/documentation checks passed.

The age evidence UI retains parser notes and states that the age rule checked the
complete quoted requirement. Existing saved evidence remains historical; new executable
identity yields new operation IDs. No new cases/trials were inserted into the API
catalog; CLI fixtures are isolated. Search defaults, weights, parser/index artifacts
and learned-model thresholds are unchanged. Existing Starlette/httpx and Torch
deprecation warnings remain unrelated to the coverage extension.

## Provenance and reproduction

Git base commit before this extension: `35f876cc4b7069a2909cf6ab19a4fdc4671c4adf`.
The base commit alone does not identify uncommitted changes; reports include current
source fingerprints, and both before/after source exports preserve actual bytes.

| Identity | SHA256 |
|---|---|
| Baseline source export inventory | `e85ba101fd55a7f721fbb8f6fe7de79e3045d907f1f1a6a024192400042094cc` |
| Paired baseline manifest | `2ad0bb5a22aac5e950f7a6eb42bc3104ee18d6c855284387e971b128d7d71e4e` |
| Final verifier, including age grammar | `da82149a803dd96abc37be9289b85e28205acb6b865b73988a68b48fe9e90259` |
| New authored fixture | `1ecee7786e7ae62309b69aa0557aefb0bba57d2abde3f86b9f085151e6c3b4b0` |

`evaluation.screening_coverage verify` checks report identities, file inventories,
source alignment, current-rule reproduction and every paired count/changed decision.
Snapshots and completed reports are write-once. No raw source was changed in place.
Candidate source export: ignored `artifacts/screening-coverage-source-v2`.

Executable changes intentionally cause strict verification of the earlier independent
retrieval study against the current source to reject its code mismatch. Its immutable
results and original source export remain preserved; no 2021 holdout was rerun or tuned.

Remaining work requires independent criterion labels and better handling of complex
language. The remaining 1,429 unknowns are retained as limitations. No clinical
validation, real-patient workflow, deployment, model promotion, staging, commit or push
was performed.
