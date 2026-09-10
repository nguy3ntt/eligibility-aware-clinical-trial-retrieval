# Bounded eligibility parsing and criterion-vector checks

Date: 2026-09-08. Code was tested in the local working tree; no release commit or full-corpus/held-out validation is claimed. Raw data, models and generated reports are intentionally not published. The [operating guide](../eligibility-parsing.md) provides reproducible commands and [ADR 0009](../architecture/decisions/0009-lossless-bounded-eligibility-parsing.md) records the design.

## Question and scope

Can a deterministic parser preserve original trial eligibility evidence while exposing useful section/clause/type/numeric structure, and can a small independent criterion collection faithfully store and retrieve those representations?

This is not an experiment on patient eligibility, clinical NLP generalization, relevance ranking superiority, or ANN performance. Existing dense/age-sex retrieval remains the default. The previous hybrid promotion gate remains unmet.

## Data and method

- Labelled development sample: 10 entirely invented trial-text examples with 27 manually specified exact criterion tuples. Gold fields include character boundaries, section, ordered type tags, visible conjunctions, numeric name/operator/bounds/unit and parent ordinal. Exact-trial scoring additionally requires original criterion order. Fixtures are authored rule contracts, not independent held-out labels.
- Historical audit: first 12 sorted NCT IDs from the existing 443-trial dense diagnostic, sourced from the immutable April 27, 2021 TREC archive. No sample selection was optimized for parser or retrieval scores. Archive hashes/size, member CRC and XML identity were checked before reading the original eligibility field.
- Parser: `eligibility-parser-v1`, SHA-256 `81ae1778f0c6867caa35a1b13c3798cae4b8474024d6a3fc32afc99fa02b8077`. Exact decoded text and raw source identities are retained. Sections cover the entire field; criterion spans, order, parent links and stored deterministic parses are validated.
- Vectors: section label + ancestor wording + verbatim criterion text, template `criterion-section-ancestors-verbatim-v1`; MiniLM revision `1110a243fdf4706b3f48f1d95db1a4f5529b4d41`, 384-dimensional normalized float32 cosine, CPU, four threads, seed 0, 256-token limit. Snapshot SHA-256 `1c19648419c54882486fa5522fcf25a902bee090345dd90500038c98385f1075`.
- Lexical representation: same criterion template, BM25 Lucene through bm25s 0.3.11, k1=1.2, b=0.75, English stopwords, lowercase, no stemming, corpus-frozen vocabulary/IDF, no server-side IDF modifier. Scores remain separate from cosine.
- Storage: local Qdrant 1.19.0, separate `criteria_v1`, 139 points from 12 trials, two named vectors and six payload indexes. Artifact SHA-256 `bca1cce81afe03118be7596bbb4d90e15b6cb01b568c6a84507b027738abbc03`.

## Results

| Check | Result | Interpretation |
|---|---|---|
| Exact labelled trials | 10/10 | All authored structural contracts matched |
| Exact criterion tuples | 27 correct, 0 extra, 0 missed | Development precision/recall/F1 = 1.0 |
| Historical section counts | 15 inclusion, 37 exclusion, 87 unknown | Unlabelled coverage; no inferred section for unrecognized text |
| Historical type coverage | 83 records tagged `other` | Bounded lexical tags are far from exhaustive |
| Historical numeric extraction | 1 recognized constraint | Many indirect bounds/units remain unsupported; no accuracy estimate |
| Historical review flags | 76 compound logic, 53 parent context, 16 embedded headings | Flags overlap; these are not independently usable predicates |
| Re-encoding | All 139 vectors; maximum difference 0 | Saved vectors reproduce from recorded source/template/model |
| Dense token truncation | 2/139 inputs | Full text retained; dense vector does not cover every token |
| Exact retrieval comparisons | 16 source queries × dense/sparse = 32 checks | Independent matrix/BM25 top-5 references agreed within float tolerances |
| Query replay | All 32 repeated identically | Stable live IDs and scores on the same server |
| Dense score maximum absolute error | 1.3842e-7 | Below 1e-6 absolute tolerance |
| Sparse score maximum absolute error | 1.9468e-5 | Within 1e-5 absolute + 1e-6 relative tolerance |
| Storage | Full evidence, IDs, dense/sparse vectors and indexes verified | Repeated imports idempotent; restart verification passed |

Initial original-text inspection uncovered colonless CRLF heading and CRLF paragraph boundaries that LF-focused examples missed. Both were corrected with explicit regression tests, without normalizing the preserved field. Intermediate source/vector artifacts were superseded locally and kept ignored.

Final review also identified shared exception/condition/alternative scope across semicolons. The parser now preserves the entire candidate whenever these cues are present, even when the next phrase has a recognized subject. Three regression cases cover this conservative guard. The historical sample counts and vectors were unchanged, while parser-derived identities were regenerated for the final version.

The first independent BM25 check used a fixed 1e-5 absolute tolerance and rejected two long-query sums: the largest discrepancy was approximately 0.0000155 at score 88.57. Inspection showed float32 summation differences rather than an ID/ranking/formula error. Criterion verification now uses the stated absolute-plus-relative bound, with tests that accept small scale-dependent rounding but reject material changes. Dense tolerance and all previous retrieval evaluation gates are unchanged. The failed diagnostic remains local evidence.

The current suite passed 245 tests, including source/CRC/XML validation, CRLF offsets, nested/compound clauses, invalid/unsupported units, altered evidence/checksums, malformed vectors, incompatible collection contracts, repeated loading, partial-import recovery, lexical abstention and live storage corruption. Of these, 231 are publishable tests; 14 existing local milestone tests remain ignored. Five live-server tests ran against isolated disposable collections. Lint, formatting and compilation passed. One existing Starlette/httpx deprecation warning remains.

Seven documented inspection commands also passed, including both truncated-input queries. Restarting Qdrant preserved the criterion collection. Both existing trial collections still verified at 443 points, with unchanged saved evidence and vectors. No retrieval integration, source snapshots or ranking defaults were changed.

## Reproduction evidence and limits

Local final manifests are `evaluation/reports/m7-parsing-release/experiment.json` and `evaluation/reports/m7-index-release/experiment.json`; they record implementation/data/model hashes and detailed checks. `m7-manual-commands.json` retains the documented command outputs. Source artifacts are `data/processed/criteria-source-m7-v3`; vectors are `data/processed/criterion-vectors-m7-v3`. Raw/derived artifacts and these detailed reports remain Git-ignored.

An exact match on invented development examples does not establish real-world parser accuracy. Historical records have no criterion-level gold labels here. Complex syntax, unrecognized headings, indirect quantities, cross-list alternatives, nested subheadings embedded within prose and terminology beyond the bounded patterns remain unresolved. Some records are group headings or compounds, not atomic clinical predicates. Numeric values retain their containing criterion and context; they must not be independently executed as eligibility rules. The sample is small and partly drawn from an existing judged retrieval pool, so no significance or generalization claim is appropriate.

No patient–criterion assessments were performed. Future verification must preserve uncertainty, refuse unsupported interpretations, and evaluate independent synthetic case–criterion labels before reporting any clinical-style outcome.
