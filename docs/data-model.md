# Data model

## Reranked evidence results

The optional `reranked-evidence-results-v1` CLI packet preserves candidate identity, original/final rank and dense score separately from the learned relevance logit. The reranker records pinned model/template identity, query and document hashes, full/used token counts and retained character spans. Summary spans refer to normalized renderer text; a separate verified evidence artifact retains original XML field text lists, locators, XML hash and archive/member provenance. Explanations include the validated full research-screening packet, criterion outcomes, patient fact references, blockers and unknowns. No new canonical database, eligibility probability or criterion-vector index is introduced. See [the contract and usage guide](reranking-and-explanations.md).

This document defines conceptual entities. Concrete SQLAlchemy models and migrations are introduced only after source inspection.

| Entity | Purpose | Important fields |
|---|---|---|
| `trials` | Canonical trial record | NCT ID, titles, summary, study type, phase, status, sex, age bounds, dates, content hash |
| `trial_conditions` | Conditions associated with a trial | source text, normalized term, optional terminology code |
| `trial_interventions` | Drugs, devices, procedures, or other interventions | type, name, description |
| `trial_locations` | Trial facilities and geography | facility, city, state, country, coordinates |
| `eligibility_criteria` | One atomic criterion | source section, text, type, operator, value, unit, parser version |
| `patient_cases` | Synthetic benchmark or generated patient narrative | source, external ID, raw description, synthetic flag |
| `patient_facts` | Structured facts extracted from a case | type, source span, value, negation, temporality, certainty |
| `embedding_versions` | Reproducibility contract for vectors | model, revision, dimension, distance, normalization, template |
| `ingestion_runs` | Pipeline audit | source, timestamps, counts, status, configuration |
| `retrieval_runs` | Search experiment or request | case, mode, parameters, model version, latency |
| `retrieval_results` | Ranked results and component scores | trial, rank, dense, sparse, fusion, reranker, final score |
| `criterion_assessments` | Patient–criterion output | assessment, confidence, fact evidence, model version |
| `relevance_judgments` | Benchmark ground truth | case, trial, graded label, source |

## Implemented local persistence

The bounded API implements four PostgreSQL tables through explicit Alembic migrations: `ctr_catalogs`, `ctr_cases`, `ctr_trials` and `ctr_operations`. Catalog/source identities and payload SHA-256 values are relational columns; validated JSONB retains complete versioned evidence, profiles, criterion assessments, explanations and operation provenance. Catalog-scoped foreign keys preserve source ownership. Completed operations are immutable and transactional; repeat requests can replay a saved result under the same request/source/code/runtime identity.

This is a deliberate bounded implementation, not completion of every proposed normalized entity above. Earlier references below to deferred SQL describe the stage when those contracts were introduced. See [ADR 0012](architecture/decisions/0012-local-research-api-and-immutable-postgres-evidence.md) and [the API guide](local-research-api.md). The canonical ClinicalTrials.gov normalization proposal remains separate from the historical catalog imported here.

## Identity rules

- Preserve the ClinicalTrials.gov NCT ID.
- Generate stable internal identifiers from source plus external ID where appropriate.
- Never use a vector point’s transient position as a canonical identifier.
- Every criterion retains its parent trial and source order.
- Every derived record retains the transformation or model version that created it.

## Content hashes

Canonical source content receives a deterministic hash. Unchanged records should not be normalized, embedded, or indexed again. A hash change creates an auditable update; it does not overwrite raw source history.

## Unknown and missing values

Missing values must remain distinct from negative values. For example, an absent maximum age is not the same as a maximum age of zero, and an unmentioned medication is not evidence that the patient is not taking it.

The implemented `synthetic-profile-v1` contract preserves source and narrative hashes, exact mention/context character spans, rule version/fingerprint, assertion, certainty, temporality, and experiencer. It retains all supported mentions instead of merging them into a confirmed clinical state. Unrecognized categories and extraction issues remain explicit, and the profile is labelled non-exhaustive. Only reliable current patient age/sex facts can create a filter plan. See [ADR 0008](architecture/decisions/0008-evidence-backed-synthetic-patient-facts.md); SQL persistence remains deferred.

The implemented `parsed-eligibility-v1` contract adds exact decoded trial text, raw XML/archive provenance, contiguous section coverage, ordered criterion spans, stable parser/source-derived IDs, parent links, bounded type/quantity rules and review reasons. The separate criterion vector artifact embeds section + ancestors + verbatim wording and records token truncation without discarding evidence. It does not create a `criterion_assessments` record or resolve medical eligibility. See [ADR 0009](architecture/decisions/0009-lossless-bounded-eligibility-parsing.md).

`research-screening-v1` embeds the validated profile and parsed trial, evidence-backed criterion outcomes, rule/source identities, blocker/unknown IDs and missing information. Stored assessments can be reproduced before reuse. Rules have no invented confidence probability. Optional learned NLI advisories are separate, non-promoted text-relation outputs and never alter the screening packet. These are local JSON contracts; SQL persistence, HTTP routes and confirmed clinical eligibility remain absent. See [ADR 0010](architecture/decisions/0010-evidence-backed-screening-and-nli-advisories.md).

## Observed canonical trial proposal

This proposal follows the [500-record inspection](experiments/0001-bounded-data-inspection.md). It does not add database models or normalize source text yet. A canonical record must distinguish source identity from record version; the same NCT ID in the current API and the historical TREC corpus is not the same evidence version.

| Proposed field | Source or representation | Observed design requirement |
|---|---|---|
| `trial_id` | `protocolSection.identificationModule.nctId` | Required stable `NCT` plus eight ASCII digits; retain even when content changes |
| `source_version` | Source name, snapshot ID, response checksum, record JSON pointer | Required alongside identity; do not overwrite evidence history |
| `titles` | Brief title plus optional official title | Official title absent in 10/500 records |
| `summary`, `description` | Original brief summary and optional detailed description | Detailed description absent in 128/500; no fabricated fallback text |
| `status`, `study_type` | Original API values plus later versioned mappings | `UNKNOWN` is an explicit source value, separate from missing status |
| `phases` | Ordered list of original phase values | 18 records have two phases; explicit `NA` differs from an absent field |
| `conditions`, `interventions`, `locations` | Source-ordered arrays and original field values | Optional arrays; locations absent in 57/500, interventions in 60/500 |
| `eligibility_text` | Exact original text with source pointer | Present in all 500 but includes a placeholder; presence does not prove usable criteria |
| `sex` | Original source value, nullable in general | Do not interpret a patient's missing sex as compatible |
| `minimum_age`, `maximum_age` | Original string; later parsed quantity, unit, parse status | Preserve singular/plural units from minutes through years; bounds absent in 52/500 and 233/500 |
| `healthy_volunteers` | Nullable boolean with source presence metadata | Absent in 8/500; false must remain different from missing |
| `start_date`, `last_update_date` | Original date string plus later precision/type fields | 280 start dates are month precision, 214 day precision, six absent; do not invent a day |
| `content_hash` | Versioned deterministic canonical-content hash | Keep distinct from raw HTTP-body checksum; normalized hashing is not implemented yet |
| `validation` | Issues, original presence states, normalizer/schema version | Preserve absent/null/empty/wrong-type distinctions and all malformed source references |

For age bounds, do not convert months or years into a fixed number of days without a documented comparison policy. A missing bound remains unknown unless an explicit source convention and validation rule justify an unbounded interpretation. For phases, preserve arrays rather than reducing them to one scalar. For dates, preserve precision and any actual/estimated source attribute.

Synthetic case identity is `(benchmark_release, topic_id)`, e.g. `trec-ct-2022:1`. Judgment identity is `(benchmark_release, topic_id, trial_id)` with original integer grade, qrel line, source checksum, and corpus version. Do not merge topic numbers across releases or assume an unjudged pair is irrelevant.

Ten topic–trial source reviews support this proposal. Retrieval experiments must retain a distinct historical corpus version and must not replace it with current API content. No learned outputs or deterministic eligibility rules exist at this stage.

The proposal is accepted as the input contract for the retrieval renderer, subject to validation against the historical corpus. SQL models and migrations remain deferred until retrieval experiments demonstrate a persistence requirement.
