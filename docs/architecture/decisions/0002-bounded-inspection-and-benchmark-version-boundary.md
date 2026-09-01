# ADR 0002: Keep bounded current-source inspection separate from historical benchmarking

- Status: accepted
- Date: 2026-08-31
- Owners: project maintainers

## Context

The data design needs observed source data before database schemas or retrieval infrastructure. The official TREC 2022 topics are synthetic, but its judgments concern the April 27, 2021 trial snapshot. Fetching today's record by the same NCT ID does not recover that historical version.

## Decision

Select 500 unique TREC 2022 judged trial IDs using a versioned SHA-256 ordering and fixed seed. Fetch current ClinicalTrials.gov records only for those IDs in batches of at most 100. Cap any run at 1,000 selected IDs. This provides bounded field inspection and potential review pairs without downloading the full historical corpus.

Preserve source responses in new, write-once local directories with request metadata, timestamps, checksums, code hashes, and before/after API version metadata. Separate acquisition from deterministic offline profiling. Do not introduce a database, vector index, models, or automatic eligibility decisions.

Preserve every qrel's topic and source-line link. Represent current-record coverage as `available`, `missing_from_api`, or `outside_bounded_sample`. Historical evidence remains explicitly `not_loaded`; none of these joins is benchmark-comparable yet. Retain source benchmark labels without presenting them as current assessments.

Treat the observed stale year attribute in `topics2022.xml` as a narrow, checksummed source exception, with a visible warning. Never rewrite the raw source or generically relabel 2021 files.

## Consequences

- Replaying saved bytes reproduces inspection outputs without network access.
- Live refetches need not reproduce the same content; the API data timestamp and bytes can change.
- This is a sample of judged IDs and is biased toward the historical benchmark pool. It does not justify a registry-wide missingness estimate or a medical-area specialization.
- All source downloads and generated outputs stay Git-ignored. Reviewed aggregate notes, code, and tests may be published.
- Ten manual source-consistency reviews complete the bounded inspection without producing eligibility assessments.
- All 500 selected trial IDs are traceable to current records and judgments. The full historical corpus remains a mandatory prerequisite for benchmark retrieval; no TREC score is claimed from this sample.
- Schema fields remain proposals, not premature database migrations.

## Alternatives considered

- Full corpus download: exceeds the next bounded-inspection step.
- Treat current API records as the benchmark corpus: invalidates version alignment.
- Sample only recently updated records: less direct connection to the intended benchmark topics and judgments.
- Silently correct the topics header: loses evidence of a real source inconsistency.

## Validation

Offline tests cover strict topic/qrel validation, deterministic selection, explicit coverage gaps, immutable run directories, checksum failures, transient HTTP errors, API version drift, and replay identity. The first observed run is documented in [experiment 0001](../../experiments/0001-bounded-data-inspection.md).

The source review also checks current-record chronology against the April 27, 2021 cutoff. A date at or before the cutoff is recorded only as `no_registered_update_after_cutoff`; it is never promoted to checksum-verified historical equivalence. Aggregate review findings are documented in [experiment 0001](../../experiments/0001-bounded-data-inspection.md).

Primary references: [TREC 2022 track](https://www.trec-cds.org/2022.html), [NIST topics and qrels](https://trec.nist.gov/data/trials2022.html), and [ClinicalTrials.gov API](https://clinicaltrials.gov/data-api/api).
