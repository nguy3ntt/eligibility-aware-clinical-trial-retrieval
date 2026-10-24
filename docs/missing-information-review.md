# Prioritised missing-information review

New screening results include a separate, source-linked review worklist. It helps a
reviewer see which existing synthetic-record gaps are reused by unresolved checks.
It never edits a patient fact, changes screening, recommends ordering tests or assigns
clinical urgency. Unknown remains unknown until a future, separately validated input
is screened again. The interface does not accept patient-text or fact edits.

See [the reviewed audit](experiments/0017-missing-information-review.md) and
[ADR 0023](architecture/decisions/0023-source-linked-missing-information-review.md).

## What the worklist contains

**Fact review:** only explicit gaps already reported by recognised deterministic
predicates. These include missing, uncertain, conflicting or non-patient evidence and
measurements recorded in a different unit. A question is never inferred from a keyword,
criterion type, missing extraction category or learned NLI advisory. Reviewing an
existing record is different from recommending a new measurement.

**Criterion interpretation first:** unsupported predicates, unknown preambles,
ambiguous scope and other interpretation limits. More patient data alone cannot be
assumed to resolve these. A grouped global-scope warning suppresses local fact questions.

**Unknowns in settled logic branches:** grouped leaves that remain unknown while an
ancestor expression is already known. For example, a true branch settles an OR; the
other missing branch is retained for provenance but does not become an active question.
An entirely inapplicable conditional does not create a request for its consequent.

Every reference keeps original assessment, trial, criterion and optional grouped-node
IDs, source character spans, reasons, missing-information strings and cited facts.
Known likely-exclusion blockers remain explicit in the plan and the original evidence.

## Ordering and deduplication

The service groups references by canonical fact name and requested unit. Two age
requirements in years share one review item; hemoglobin in g/L and g/dL stay separate.
Conflicts and uncertainty remain visible through each reference. No unit conversion,
new diagnosis or hypothetical patient value is introduced.

Items are ordered by:

1. Number of included trials without an existing screening blocker.
2. Number of distinct original source criteria linked to the item.
3. Number of included trials linked to the item.
4. Canonical fact name and unit for stable ties.

These are reuse counts, not clinical importance, predicted information gain or a
probability of eligibility. No blockers is not proof of eligibility; unsupported
criteria may remain. Satisfying one missing check does not necessarily settle its
group, section or entire trial. Duplicated tree wrappers do not inflate criterion counts.

The browser shows only the selected case–trial pair. The reusable service
`prioritise_missing` can aggregate 1–10 different trials of exactly the same synthetic
case/version; the historical audit exercises all three original trials per case.
Do not interpret this bounded worklist as a search over the entire registry.

## Manual browser checks

Start the existing local stack using the [workspace guide](research-workspace.md),
then open <http://127.0.0.1:5173>:

1. Select **Invented demonstration · reranking-demo**, open **Eligibility evidence**
   and choose **NCT90009001**. Click **Screen selected pair**.
2. Find **Prioritised information review** above the complete criterion list. Expect
   **Verify creatinine (mg/dL)**, linked-criterion counts and expandable source quotes.
   The ordinary outcome remains **insufficient information**.
3. Run the same pair again. Expect **Saved replay**, the same plan ID and the same
   quotes/counts. Opening the saved screening in the experiment dashboard also retains
   the recorded worklist; it does not calculate a new one.
4. Switch to **NCT90009003** and screen it. Expect **likely exclusion** and the notice
   that existing blockers remain. A review worklist must not remove them.
5. Select synthetic case **29** and trial **NCT00258570**, enable the experimental grouped
   logic comparison and screen it. Inspect the separate interpretation queue and grouped
   mode notice. Original screening evidence and the grouped interpretation remain distinct.

The audit's historical age-unit example (case 45/trial NCT00676351) is outside the
interactive catalog and cannot be selected here. Inspect it in the saved audit instead;
the invented CLI example below demonstrates deduplication without expanding the catalog.

Old saved packets without a worklist remain readable. They explicitly say that no
review ordering was recorded; opening historical evidence never manufactures a plan.
Retrieval defaults, reranking choices and eligibility rules are unchanged.

## Manual CLI examples

From the repository root, these invented examples need no services or model:

```powershell
..\.venv\Scripts\python.exe -m pipelines.screening --fixture evaluation/data/fixtures/missing_information_review.json --pair-id review-deduplicate-age --review
```

Expect age/year first, linked to two source criteria, then creatinine/mg/dL linked to
one. All three checks and the trial remain unknown/insufficient information. This
demonstrates deduplication and count-based ordering, not newly inferred facts.

```powershell
..\.venv\Scripts\python.exe -m pipelines.screening --fixture evaluation/data/fixtures/missing_information_review.json --pair-id review-or-settled --grouped --review
```

The grouped OR is already true from the age evidence. Expect no active review items
and one retained unknown in a settled branch. The separate ordinary flat assessment
stays conservative; the plan identifies itself as grouped. These fixtures are not
inserted into the API's immutable catalog.

## Reproduce the audit

The prepared audit uses the existing verified `screening-coverage-after-v2` assessments,
not new trial acquisition or 2021 case reuse:

```powershell
..\.venv\Scripts\python.exe -m evaluation.missing_information_review verify --output-id missing-information-review-v1
```

Expect complete status, all 21 authored contracts passing and all 150 original
assessments/statuses unchanged. Ordinary mode has one age-unit item linked to two
unknown criteria; 1,427 unknown criteria remain interpretation tasks. Grouped counts
are leaf references and must not be compared directly with flat criterion counts.

For a fresh reproduction, use `evaluate --output-id <fresh-id>` followed by `verify`
with that ID. Existing destinations are rejected. Protocol, source/implementation
fingerprints, original assessments, pair plans, per-case aggregate plans and metrics
stay under ignored `evaluation/reports/`. Strict verification after future code changes
requires the frozen matching source. No model inference or database/index modification
is needed. Run HTTP and browser suites sequentially against the single-operation API.

## Limits

The new examples are authored development contracts, not independent human review or
clinical-utility labels. The historical audit measures reproducibility and disposition
of existing unknowns, not accuracy, workload reduction or improved eligibility coverage.
No information-gain model, acquisition cost, expected clinical benefit or supported
decision is learned from this ordering. It remains a bounded academic research aid.
