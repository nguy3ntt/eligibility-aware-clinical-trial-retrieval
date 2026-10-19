# Bounded screening coverage

This extension adds explicit whole-clause age predicates and same-unit platelet facts
to deterministic research screening. It preserves uncertain outcomes and full source
context. See [ADR 0018](architecture/decisions/0018-bounded-screening-coverage.md) and
the [reviewed experiment](experiments/0013-bounded-screening-coverage.md).

## Behavior you can inspect

`Ages 3 to <9 years` accepts an exact current age of 3 years and rejects age 9 years.
`Age >=18 and <65 years` preserves both inequalities. `Age 18 years or older` includes
age 18; `>60 years of age` excludes age 60. Age units must match the patient fact: a
year value is not silently converted to months. Bare `>18 years` lacks an explicit age
subject/suffix and remains unsupported.

Platelet labels include `Platelets` and `Platelet count`. The explicit units `/mm3`
and `/mm³` share a spelling normalization; `x10^9/L` is a separate unit. Comparing
150000 `/mm3` against 150 `x10^9/L` remains unknown: this implementation does not rescale
the value. Reliable current facts and the complete trial predicate are required.

Full clauses containing additional disease requirements, timing, visits or exceptions
remain unsupported. All existing context guards remain. The only newly accepted `or`
is inside a fully recognized age-bound phrase; an unrelated `or`, shared exception,
unresolved preamble or nested group still blocks unsafe interpretation. Missing facts
never satisfy a criterion. Optional learned NLI remains separate and NOT PROMOTED.

## Manual checks without services or models

Run from the nested repository. In the prepared Windows workspace, replace `python`
with `..\.venv\Scripts\python.exe` if the virtual environment is not activated.

```powershell
python -m pipelines.screening --fixture evaluation/data/fixtures/screening_coverage.json --pair-id coverage-age-open-upper-fail
python -m pipelines.screening --fixture evaluation/data/fixtures/screening_coverage.json --pair-id coverage-platelets-pass
python -m pipelines.screening --fixture evaluation/data/fixtures/screening_coverage.json --pair-id coverage-platelets-unit-mismatch
python -m pipelines.screening --fixture evaluation/data/fixtures/screening_coverage.json --pair-id coverage-age-global-exception
```

Expected results, in order:

1. **likely_exclusion**: the invented 9-year-old case violates the explicit `<9` upper
   bound. The decision cites `9-year-old` and the original full criterion span.
2. **potential_match** under the authored one-criterion example: platelet count 150
   `x10^9/L` satisfies `>=150 x10^9/L`, with a cited patient measurement.
3. **insufficient_information**, with `units_differ_no_conversion`.
4. **insufficient_information** for both criteria: an exception in another section
   still blocks the standalone age comparison.

All are explicitly invented development examples, not new catalog patients or trials.
No arbitrary narrative is accepted by the API. Other examples cover approximate,
conflicting, historical, family and invalid-unit measurements.

## Evaluate authored contracts

```powershell
python -m evaluation.screening --output-id my-original-screening-check-01
python -m evaluation.screening --fixture evaluation/data/fixtures/screening_coverage.json --output-id my-expanded-screening-check-01
python -m pytest backend/tests/test_screening.py backend/tests/test_screening_coverage.py -p no:cacheprovider
```

Use fresh report IDs. Expect the original **34/34 pairs, 41 criteria** and new
**31/31 pairs, 35 criteria** to match their authored outcomes. The new fixture includes
19 deliberately unknown outcomes. These exact-match checks are development contracts,
not an estimate of clinical accuracy or independent generalization.

## Inspect the paired historical audit

```powershell
python -m evaluation.screening_coverage verify --output evaluation/reports/screening-coverage-after-v2
```

Expect `status: verified`, **150 pairs and 1,434 criteria**. Under ignored
`evaluation/reports/`, inspect:

| Folder/file | What it preserves |
|---|---|
| `screening-coverage-before-v1/manifest.json` | Original release hashes, source identities and reproduced v1 implementation |
| `screening-coverage-before-v1/assessments.json` | All original 150 assessments |
| `screening-coverage-after-v2/report.json` | Paired counts, remaining abstention reasons, transitions and implementation hashes |
| `screening-coverage-after-v2/changed-decisions.json` | Every changed criterion with cited facts and full trial source |
| `screening-coverage-after-v2/assessments.json` | Complete fresh v2 assessments, including every unresolved requirement |

The audit changes five criteria from unknown to supported: four satisfied and one
violated. Trial summaries become 149 insufficient-information and one likely exclusion.
There are no new potential matches in this historical set. No independent accuracy is
measured. The original source report and the intermediate v1 candidate report remain
untouched; v2 is the final report after additional safety checks.

To reproduce the candidate comparison from the preserved baseline:

```powershell
python -m evaluation.screening_coverage evaluate --output evaluation/reports/my-screening-coverage-01
python -m evaluation.screening_coverage verify --output evaluation/reports/my-screening-coverage-01
```

`capture` is a **pre-change** operation: it deliberately refuses to relabel the current
v2 implementation as the original baseline. On a fresh installation, the original
release packet and original source/runtime are required to recreate that baseline.
The reproducible current-rule checks on invented fixtures do not need those private artifacts.

## Existing browser/API

Follow the [workspace guide](research-workspace.md) to start the prepared local services.
Restart the API after changing source so it loads v2. Fresh screening packets report
`bounded-screening-rules-v2`; historical operations retain their previous verifier and
explicit Saved Replay label. Case facts use `synthetic-facts-rules-v2`.

The new invented CLI fixtures are intentionally not added to the immutable API catalog.
The existing browser evidence panel displays the same outcome, cited fact, rule and
source fields. It has no new feature switch. Normal search remains exact dense plus
legacy age/sex with no reranking; models, catalogs and vector indexes are unchanged.

For a browser check, choose **trec-ct-2022:29**, open **Eligibility evidence**, select
**NCT00258570** and screen it. Expect two age clauses with rule
`whole-age-predicate-v2`, both supported by the cited `57-year-old` fact. The overall
trial remains **insufficient information** because other requirements are unresolved.
Original parser review notes stay visible beside an explanation of the full-quote age
check. This pair uses the existing public trial/synthetic-case catalog.

All historical packets, raw data, private tracking and source exports remain ignored.
The publishable additions are source, tiny invented fixtures, tests and reviewed
documentation. The owner handles GitHub commits and publication manually.
