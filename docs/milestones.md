# Milestones

The project is intentionally built as a sequence of useful, independently reviewable releases. A later pivot should reuse earlier ingestion, retrieval, evaluation, and API components rather than require a rewrite.

**Active milestone: Milestone 1 — Data understanding (in progress, 2026-08-31).**
The first bounded inspection is recorded in [experiment 0001](experiments/0001-bounded-data-inspection.md).
Milestone 0's installation, health test, lint, format, and compilation checks have run successfully.

## Milestone 0 — Foundation

**Goal:** establish a safe, reproducible project boundary.

Deliverables:

- repository and package structure;
- environment and infrastructure templates;
- project charter, architecture, safety, and evaluation documentation;
- minimal health endpoint;
- linting and test configuration;
- Architecture Decision Record template.

Exit criteria:

- the repository can be installed;
- tests and static checks run;
- the API health endpoint responds;
- no database or dataset is needed for the health check.

## Milestone 1 — Data understanding

**Goal:** design from observed source data rather than assumptions.

Deliverables:

- bounded ClinicalTrials.gov sample of approximately 500–1,000 trials;
- TREC topics and qrels loader;
- field inventory and missingness report;
- representative eligibility-format examples;
- canonical schema proposal;
- ten manually inspected patient–trial pairs.

Exit criteria:

- every TREC identifier can be traced to its topic, judgment, and trial record;
- raw source snapshots are immutable;
- transformations are reproducible;
- malformed or missing data are documented.

Pivot checkpoint: narrow the medical area here if the observed data support an oncology, rare-disease, Australian-site, or another justified specialization.

Progress for the first inspection:

- [x] Acquire 500 public current-API trial records without a full-corpus download.
- [x] Load and validate official synthetic TREC 2022 topics and qrels.
- [x] Preserve immutable source snapshots, request metadata, and checksums.
- [x] Profile fields, missingness, and representative eligibility formats.
- [x] Propose canonical fields based on observations.
- [ ] Complete ten human patient–trial pair reviews; an evidence-linked worksheet is prepared.
- [ ] Resolve historical trial-record coverage for benchmark judgments. All topic/judgment links are checked, but only 627 judgments join to current sample records; none have a loaded April 2021 trial record.

Do not mark Milestone 1 complete or report TREC retrieval performance from the current-API sample. Next work remains inside this milestone: review the worksheet and plan bounded access to historical trial evidence, recording unresolved IDs explicitly.

## Milestone 2 — BM25 baseline

**Goal:** establish a credible lexical baseline before neural retrieval.

Deliverables:

- trial text renderer;
- BM25 index and query runner;
- experiments over alternative field combinations;
- age/sex filtering baseline;
- nDCG, MRR, Precision, Recall, and error-analysis report.

Exit criteria:

- rankings and metrics are reproducible from a saved configuration;
- run files retain trial identifiers and ranks;
- good and bad queries are manually analysed.

## Milestone 3 — Dense exact retrieval

**Goal:** test whether dense biomedical representations add value.

Deliverables:

- versioned embedding interface;
- lightweight general embedding baseline;
- biomedical embedding candidate;
- batched document encoding;
- exact cosine similarity retrieval;
- comparison against BM25.

Exit criteria:

- model name, revision, dimension, normalization, and input template are recorded;
- embedding time and storage are measured;
- dense retrieval is evaluated rather than assumed superior.

## Milestone 4 — Qdrant and approximate search

**Goal:** introduce a real vector database and quantify ANN trade-offs.

Deliverables:

- local Qdrant service;
- `trials_v1` collection and payload indexes;
- idempotent batched upserts;
- HNSW retrieval;
- exact-versus-ANN recall and latency evaluation;
- snapshot and rebuild procedures.

Exit criteria:

- vectors persist across restarts;
- ANN Recall@10 is measured against exact search;
- the index is reproducible from canonical data.

## Milestone 5 — Hybrid retrieval

**Goal:** combine lexical precision and semantic recall.

Deliverables:

- sparse representation in Qdrant;
- dense and sparse retrieval branches;
- Reciprocal Rank Fusion;
- structured payload filters;
- per-result score and rank provenance;
- dense/sparse/hybrid ablation.

Exit criteria:

- each result identifies which branch retrieved it;
- incompatible raw scores are not added directly;
- hybrid improvement is supported by evaluation.

Pivot checkpoint: release 0.2 is already a valid standalone Vector DB project. Continue only if eligibility intelligence remains the desired differentiator.

## Milestone 6 — Patient fact extraction

**Goal:** transform synthetic patient narrative into auditable facts.

Deliverables:

- structured patient profile;
- age, sex, condition, medication, treatment, and measurement extraction;
- negation, temporality, and certainty fields;
- rule test suite;
- filter builder.

Exit criteria:

- every structured fact links back to source text;
- uncertain and missing facts remain explicit;
- extraction failures are inspectable.

## Milestone 7 — Eligibility parsing

**Goal:** convert long eligibility text into traceable atomic criteria.

Deliverables:

- inclusion/exclusion section parser;
- clause splitter;
- criterion-type classifier;
- numeric constraint and unit parser;
- manually labelled evaluation sample;
- `criteria_v1` vector collection.

Exit criteria:

- original trial wording and order are preserved;
- parsed criteria can be traced to source fields;
- parser accuracy is measured on labelled examples.

## Milestone 8 — Eligibility verification

**Goal:** distinguish relevant-and-eligible from relevant-but-excluded.

Deliverables:

- deterministic checks for age, sex, and reliable numeric rules;
- semantic patient–criterion verifier;
- satisfied/violated/unknown/not-applicable outcomes;
- blocking-criterion and missing-information reports;
- criterion- and trial-level evaluation.

Exit criteria:

- no trial is called eligible only because no contradiction was found;
- deterministic and learned decisions are distinguishable;
- evidence supports every decision;
- high-confidence precision and calibration are reported.

## Milestone 9 — Reranking and explanations

**Goal:** improve final precision and produce auditable output.

Deliverables:

- cross-encoder reranker over a bounded candidate set;
- deterministic explanation templates;
- field- and criterion-level provenance;
- quality-versus-latency experiment.

Exit criteria:

- reranking benefit is measured;
- every final output includes evidence;
- explanations do not introduce unsupported medical claims.

## Milestone 10 — FastAPI application

**Goal:** remove notebook dependence and expose a stable application contract.

Deliverables:

- search and screening endpoints;
- trial and case endpoints;
- experiment endpoints;
- PostgreSQL repositories and migrations;
- OpenAPI documentation;
- integration tests.

Exit criteria:

- a complete request works through the API;
- failures return structured errors;
- PostgreSQL and Qdrant integration tests pass.

## Milestone 11 — React interface

**Goal:** make the system understandable to a portfolio reviewer.

Deliverables:

- search workspace;
- extracted-patient-fact review;
- trial and criterion detail views;
- eligibility evidence panel;
- retrieval laboratory;
- experiment dashboard.

Exit criteria:

- the primary workflow needs no command-line interaction;
- uncertainty and safety language are visible;
- retrieval and eligibility scores are not conflated.

## Milestone 12 — Benchmark release and hardening

**Goal:** create a reproducible portfolio release.

Deliverables:

- full selected TREC benchmark run;
- incremental ClinicalTrials.gov ingestion;
- model migration and index rebuild procedures;
- performance and failure-recovery testing;
- automated CI;
- architecture and experiment report;
- demo recording and screenshots.

Exit criteria:

- a clean environment can reproduce the reported experiments;
- limitations and negative results are documented;
- no private medical information is present;
- release artifacts identify code, data, and model versions.
