# Experiment 0001: Bounded source inspection

- Date: 2026-08-31
- Milestone: 1, data understanding — in progress
- Pipeline: `m1-inspection-v1`; no retrieval model, embeddings, scores, or eligibility decisions
- Raw snapshot: `data/raw/m1-20260831-500-v2/`
- Reviewed profile: `data/interim/m1-20260831-profile-v2/`
- Code state: uncommitted working files at execution; exact pipeline source hashes are saved in both manifests

## What was run

Loaded the official [TREC 2022 synthetic topics](https://www.trec-cds.org/2022.html) and [NIST judgments](https://trec.nist.gov/data/trials2022.html). Selected 500 unique judged trial IDs using SHA-256 ordering with seed `trec-2022-inspection-v1`, then downloaded their current records through the [ClinicalTrials.gov API v2](https://clinicaltrials.gov/data-api/api) in five explicit-ID batches of 100.

API version was `2.0.5`, with data timestamp `2026-08-28T09:00:06` before and after acquisition. The raw snapshot, including manifests and sidecars, is 13,418,002 bytes. Every original response body remains local and unchanged.

| Measure | Observed value |
|---|---:|
| Synthetic topics | 50 |
| Judgments | 35,394 |
| Unique judged trial IDs | 26,585 |
| Requested / received current trial records | 500 / 500 |
| Missing requested IDs | 0 |
| Judgment grade 0 / 1 / 2 | 28,419 / 3,036 / 3,939 |
| Judgments linked to a current sample record | 627 |
| Judgments outside the bounded current sample | 34,767 |
| Historical trial records loaded | 0 |
| Observed JSON paths, with array positions folded to `[]` | 477 |
| Selected-field type validation issues | 0 |
| Human review pairs prepared / completed | 10 / 0 |

Zero type issues does not establish semantic validity. The checks cover IDs, topic/judgment relationships, source shapes, and outer types of selected fields; they are not full clinical validation.

## Findings that affect the schema

All 500 records contained brief titles, brief summaries, conditions, status, study type, sex, and eligibility text. Optional fields must remain optional:

| Field | Absent records | Percentage of this sample |
|---|---:|---:|
| Maximum age | 233 | 46.6% |
| Detailed description | 128 | 25.6% |
| Phase | 114 | 22.8% |
| Interventions | 60 | 12.0% |
| Locations | 57 | 11.4% |
| Minimum age | 52 | 10.4% |
| Enrollment count | 14 | 2.8% |
| Official title | 10 | 2.0% |
| Healthy-volunteer flag | 8 | 1.6% |
| Start date | 6 | 1.2% |

The sample contains 386 interventional and 114 observational studies. Phase is absent for the 114 observational records, while 173 other records explicitly report `NA`. Another 18 contain two phase values. Missing and explicitly not-applicable values must not collapse into the same scalar.

Age strings use `Day`, `Days`, `Minute`, `Minutes`, `Months`, `Weeks`, `Year`, and `Years`. Preserve original quantities and units before introducing conversion rules. Of the start dates, 280 have seven-character month precision, 214 have ten-character day precision, and six are absent. Do not invent exact days from partial dates.

Status counts: 338 completed, 86 unknown, 37 terminated, 17 withdrawn, 13 recruiting, seven active/not recruiting, one suspended, and one not yet recruiting. This historical judged-ID sample is not a current recruitment search or a representative population sample.

The [schema proposal](../data-model.md) records these consequences without adding migrations or storage infrastructure.

## Eligibility formats and source inconsistencies

459 records contain both literal inclusion/exclusion heading markers; 41 do not. This is a text-format observation, not parser accuracy. The local example file retains source pointers and up to six texts in each marker category.

Representative records, all from `ctgov-001.json`, include:

- `NCT00005251`: the entire eligibility field is the placeholder `No eligibility criteria`. It counts as a present string but is separately flagged as a placeholder, not interpreted as unrestricted eligibility.
- `NCT00001672`: eligibility is expressed as paragraphs without the usual two headings.
- `NCT00006259`: dense text uses domain-specific headings such as disease characteristics instead of the expected inclusion/exclusion structure.

The official `topics2022.xml` file has 50 topics but retains a `2021 TREC Clinical Trials` task attribute. The exact observed bytes have SHA-256 `c5d37709ba14f6cb341b0bea35a7f43bd1cf93647f939659667975229a7abe91`. The loader records this discrepancy and accepts only that checksummed exception; changed mismatched files fail for inspection. Release provenance comes from the official 2022 download location, not a silent rewrite of the raw XML.

The API also emitted a trailing pagination token after all 100 explicitly requested IDs had arrived. The connector stops by requested-ID coverage, with a regression test; it does not follow that cursor into additional records. Earlier failed local attempts were retained rather than overwritten.

## What this does not establish

TREC judgments concern the **April 27, 2021** trial corpus. The organizers identify that fixed corpus on the [2022 track page](https://www.trec-cds.org/2022.html). Today's record with the same ID can have different criteria, status, or other content. Every generated judgment trace therefore records `historical_trial_status="not_loaded"` and `benchmark_comparable=false`.

No BM25 or dense retrieval baseline was run, no TREC performance metric was computed, and no source label was converted into a current eligibility assessment. Source grades remain reference labels only. The worksheet includes original synthetic topic text, qrel lines and checksums, current trial evidence, and a pending review status. Missing case facts remain unknown; any later potential-match or likely-exclusion assessment requires evidence and professional review.

These results do not yet justify narrowing the project to a medical specialty. The ten human reviews and historical source-version coverage are still outstanding, so Milestone 1 is not complete.

## Reproduction and checks

With the saved local snapshot, run:

```bash
python -m pipelines.inspection profile --run-id m1-20260831-500-v2 --output-id inspection-replay
```

Use a fresh output directory. The acquisition command and limitations are documented in [pipelines/README.md](../../pipelines/README.md). A new live fetch preserves the same selected IDs only while the qrels and configuration remain unchanged; current trial content may still differ.

- Raw manifest SHA-256: `3193f391de6b76a70c456f13ce315992cd4b2689171bfb03632eac72d964fa18`.
- Reviewed `profile.json` SHA-256: `8e7e0dacd2ea3729a8fab17c83b3197382d07c35cda72054e0d9081f337129bd`.
- Automated verification: 45 tests passed; Ruff lint/format and compilation passed. Tests include health, source-validation failures, immutable snapshots, checksum tampering, bounded requests, version drift, and deterministic replay. The freshly installed Starlette test client emits one non-failing upstream `httpx` deprecation warning; no dependency migration was added in this milestone.
- Replayed the full 500-record snapshot offline into a second directory: all ten output files, including the manifest, were byte-identical. The worksheet covers ten distinct topics and all three source judgment grades, with every review still pending.

Only this reviewed aggregate narrative, implementation, tests, and supporting documentation belong in the manual Git commit. Raw files, generated profiles/traces/worksheets, virtual environments, and local agent instructions remain ignored.
