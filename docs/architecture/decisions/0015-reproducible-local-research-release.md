# ADR 0015: Reproducible local research release

- Status: accepted; execution evidence must be reported separately
- Date: 2026-09-12

## Context

The browser workflow is complete, but the dense/hybrid quality experiments use a 443-trial judgment-selected pool. A portfolio release needs an actual full-corpus comparison, resumable data processing, independent current-registry updates, reproducible checks and an honest demonstration. The local drive has limited free space; active application evidence must remain intact.

## Fixed benchmark protocol

Use every one of the 375,580 trials in the validated April 27, 2021 render and all 50 official synthetic TREC 2022 topics. Require the existing exact input hashes; never substitute the judged pool. The selected full-corpus systems are title/condition BM25, exact MiniLM dense, and equal-weight RRF, each with and without the existing legacy age/sex filter. RRF uses constant 60 and branch depth 100. Add fixed hybrid reranking depths 10 and 20 with the existing pinned cross-encoder and summary-input policy. Reranking adds text beyond the matched title-only baseline; disclose that confound. Select configurations before observing these metrics, with no tuning or default promotion.

Retain the earlier six-configuration full-corpus BM25 experiment as historical context, not as a matched title-only comparison. All new runs use depth 100, so MRR is truncated at 100. Use the established grade-based metrics and record paired, seeded bootstrap intervals as exploratory uncertainty, not held-out significance or clinical accuracy. Pooled unjudged trials receive zero gain without being declared irrelevant. Preserve full original ranks, branch scores and reranker inputs. TREC run files for reranked systems use monotonic rank surrogates so readers cannot accidentally reorder a negative learned-score prefix behind a positive base-score tail.

A separate full-render index stores normalized float32 vectors in checked shards. Length-based batching reduces padding; vectors and token counts are restored to original row order. An intent manifest fixes sources, model, runtime and batching configuration. Only committed, checksummed shards are resumed; incomplete attempts remain inspectable. No raw files, active Qdrant collection or API catalog are overwritten. Full-corpus HNSW and a full criterion-vector index are not added: existing bounded ANN/recovery measurements remain distinct from the full-corpus exact ranking experiment.

For the final reranked top-three results, reconstruct original XML and use the existing full-context deterministic explanation/screening pipeline. Report coverage and unknowns, not accuracy without criterion judgments. Learned screening remains non-promoted.

## Incremental registry boundary

Acquire a fixed inclusive last-update date window through the official API, with explicit record/page bounds and optional NCT-ID scope. Preserve response bytes, checksums, request/cursor provenance and API data timestamps. Resume committed pages only when configuration and API identity agree. Detect invalid records, cursor loops, budget exhaustion and changing registry versions; none may publish a completed snapshot or advance a watermark.

Materialize a new current-registry artifact from a complete snapshot plus a verified previous artifact. Require matching scope and overlapping, non-regressing windows. Count added, changed and unchanged records using stable IDs and canonical content hashes; retain absent records because an update stream does not prove deletion. Keep source locators and lineage. Updating current registry data never changes historical benchmark records or the application's curated catalog.

## Release and safety boundaries

Add CI for the publishable Python and frontend checks, document clean-environment setup, and record exact local dependency/model/source identities. Validate migrations and rebuild/recovery procedures against isolated destinations. Record browser demo material using public trial records and synthetic cases only. Generated recordings, screenshots, raw data, model weights and local tracking remain ignored; publish only reviewed aggregate documentation and reproducible source/configuration. The user handles commits and publishing manually.

Do not add public deployment, accounts, external inference or medical decision claims. A successful release check means the reported engineering experiment is reproducible; it does not mean a retrieval method or clinical eligibility claim has earned promotion.
