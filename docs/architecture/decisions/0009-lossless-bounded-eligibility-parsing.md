# 0009 — Lossless bounded eligibility parsing and criterion vectors

- Status: accepted
- Date: 2026-09-08

## Context

Retrieval representations flatten whitespace and cannot reliably recover original list boundaries. Patient facts already retain source evidence, but comparing facts to criteria requires equally auditable trial-side records. Nested lists, alternatives, exceptions, missing headings and nonstandard quantities must not become unsupported eligibility decisions.

## Decision

Read the original `eligibility/criteria/textblock` from the frozen historical XML selected by the verified dense artifact. Check archive SHA-256/size, member CRC, XML structure and NCT identity. Preserve the decoded field exactly, including character offsets, line endings and section coverage; raw XML and archive hashes preserve the separate byte-level provenance. Never rewrite raw snapshots.

Use a versioned deterministic parser. Recognize explicit inclusion/exclusion headings, list markers, blank-line paragraphs and a limited set of safe semicolon boundaries. Preserve wrapped lines. Keep compound logic and exceptions together where splitting would discard context. Preserve indented parent links and expose unknown sections, unsupported quantities, unclassified types, embedded headings and placeholder statements for review. This is a bounded clause representation, not a complete Boolean or clinical-language parser; some records remain compound.

Each criterion ID hashes trial/source/field identity, original text, parser fingerprint and span. Order is explicit. Reparse stored evidence before indexing; checksums alone do not establish semantic consistency. Numeric rules recognize explicit labels, operators/ranges and units, without unit conversion, implied thresholds or eligibility inference.

Build a separate, at-most-512-point `criteria_v1` diagnostic from at most 16 selected trials. Use `criterion_dense` (pinned MiniLM, 384 dimensions, normalized cosine) and `criterion_sparse` (the existing frozen-corpus Lucene BM25 factorization). The input template is section label, ancestor wording and verbatim criterion text. Record this template honestly as the lexical representation; do not reuse the trial title/conditions label. Record token counts and embedding truncation, retaining complete source evidence independently.

The collection binds one immutable artifact/parser/model/vocabulary contract. Refuse incompatible existing collections before upserts; use stable UUIDs, acknowledged batches, idempotent loading, and complete payload/vector/index read-back. Queries are exact and bounded, with explicit dense or sparse scores and deterministic criterion-ID tie-breaking. Do not fuse criterion scores or add patient screening, ANN experiments, new infrastructure or a full-corpus criterion index.

## Validation and consequences

Manually specified invented examples measure exact spans, section/type/logic/numeric values, parent relationships and source order. Report development results separately from unlabelled historical coverage. Storage tests include missing/duplicate records, altered evidence, vector corruption and incompatible contracts. Re-encode all sampled records and compare live retrieval with independent matrix and BM25 calculations. Float32 BM25 sums use both absolute and relative tolerances because their scores are not bounded like cosine similarity.

The parser and labelled evaluation require only foundation dependencies. Index building/searching use the existing optional `hybrid` dependencies and local model. Source, parsed and vector artifacts remain local; only tiny invented fixtures, reusable code, reviewed methods/results and operating documentation are published. The prior dense/hybrid retrieval defaults and experimental ranking-promotion requirements remain unchanged.

Future verification must use full source context, respect compound/unknown/review-marked criteria, distinguish rules from learned outputs, and abstain when evidence is insufficient. A criterion type or extracted numeric expression is not proof that a patient satisfies or violates the full criterion.
