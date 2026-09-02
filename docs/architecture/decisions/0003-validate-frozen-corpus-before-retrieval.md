# ADR 0003: Validate the frozen corpus before retrieval

- Status: accepted
- Date: 2026-09-02
- Owners: project maintainers

## Context

TREC Clinical Trials 2022 judgments refer to the April 27, 2021 ClinicalTrials.gov snapshot used by the 2021 track. Current API records with the same NCT IDs can differ. Retrieval metrics are invalid unless documents and judgments refer to the same corpus version.

The official archive page provides five ZIP files, approximate sizes, and the snapshot date. It does not publish cryptographic checksums.

## Decision

Treat historical corpus acquisition and validation as a mandatory gate before rendering or indexing documents. Pin the five official URLs, exact observed byte sizes, and server `Last-Modified` values. Compute and retain SHA-256 values after download while explicitly recording that these are locally observed hashes rather than publisher-supplied checksums.

Download into a resumable `.incomplete` staging directory. Publish the raw snapshot atomically only after all five archives satisfy their transport metadata. Never overwrite a completed snapshot.

Offline validation must recompute archive hashes, verify ZIP CRCs and safe member paths, parse every XML record, validate NCT IDs against member filenames, reject duplicates, profile required renderer fields, and confirm complete qrel ID coverage. Every valid trial receives an archive/member/CRC provenance entry. Validation failures remain visible and disable benchmark metrics.

The TREC 2022 overview reports 375,581 records, but the downloaded archives contain 375,580 unique XML trials. The fifth archive includes a 119-byte `Contents.txt` file that explicitly declares 375,580 studies; its SHA-256 is pinned and the validator accepts only that exact metadata exception. The archive-backed count is the validation expectation, while the publication discrepancy remains documented.

## Consequences

- Current API content cannot silently enter benchmark runs.
- Interrupted multi-gigabyte downloads can resume without weakening completed-snapshot immutability.
- Raw archives and derived indexes remain local and Git-ignored.
- The manifest cannot claim publisher-authenticated hashes because the source does not provide them.
- BM25 rendering and evaluation may start only after this gate reports no archive, XML, count, duplicate-ID, or qrel-coverage issues.

## Validation

Offline tests use tiny invented XML trials and mocked HTTP responses. They cover resume behavior, changed source metadata, archive checksum tampering, unsafe paths, malformed XML, duplicate NCT IDs, missing judged IDs, provenance indexing, and path traversal.

Primary sources: [TREC 2021 Clinical Trials track](https://www.trec-cds.org/2021.html) and the [TREC 2022 overview](https://trec.nist.gov/pubs/trec31/papers/Overview_trials.pdf).
