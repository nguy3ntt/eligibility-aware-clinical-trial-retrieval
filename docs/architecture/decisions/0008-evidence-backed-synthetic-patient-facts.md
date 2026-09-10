# ADR 0008: Evidence-backed synthetic patient facts and conservative filters

- Status: accepted
- Date: 2026-09-07

## Context

Retrieval has exact dense, lexical, and RRF branches, but its historical demographic extractor has no general fact profile. Future criterion verification requires original evidence, context, and explicit unknowns. It must not infer diagnoses from symptoms or interpret unmentioned information as satisfying a criterion. Existing retrieval experiment parameters and results must remain reproducible.

## Decision

Introduce `synthetic-profile-v1` with immutable validated models for a synthetic source case, evidence spans, facts, and extraction issues. Preserve the complete synthetic narrative, original source checksum and locator, a separate narrative checksum, and zero-based end-exclusive Python character offsets. Every mention has both its exact quoted span and the containing clause as context. Fact identity depends on case ID, narrative, rule fingerprint, mention position, and concept. An updated extractor produces a new fingerprint rather than silently reusing an old profile.

Use `synthetic-facts-rules-v1`: a bounded deterministic lexicon plus transparent regular-expression context and quantity rules. Extract age, narrative sex labels, named conditions, medications, treatments, and supported measurements. Prefer longer overlapping concept mentions. Record assertion (`present`, `absent`, `uncertain`), source certainty (`asserted`, `uncertain`), temporality (`current`, `historical`, `planned`, `unknown`), experiencer, and rule identity. These fields describe the recognized wording, not verified medical truth or calibrated confidence. Do not infer age from dates, sex from pronouns, diagnoses from symptoms, or ongoing disease from a historical mention. Do not collapse contradictory mentions into a single clinical state.

The initial vocabulary contains 26 condition labels, 16 medication names, six treatment categories, and 12 measurement names (including two blood-pressure components). These are project labels, not standardized clinical terminology codes. Measurements require explicit supported units and preserve inequality/approximation operators. Do not supply missing units, dose schedules, clinical thresholds, or unimplemented conversions. Retain numeric/unit failures and clauses with no recognized fact as issues. A clause with some recognized facts may still contain unsupported information; all output is labelled non-exhaustive. No inference is made from an absent category.

`profile-demographic-filter-v1` independently re-extracts and compares the entire profile before building filters. Reject changed values, provenance, evidence, rules, or edited profiles. Only consistent, current, asserted, exact patient age/sex mentions can supply filters. Abstain on uncertain, conflicting, unanchored, unsupported-age, or sex/gender-review contexts. Relatives' and other people's facts do not restrict patient retrieval. Preserve fact IDs for each filter decision and keep non-demographic facts non-filtering. Reuse the existing Qdrant known-contradiction filter; missing trial data remain candidates, not verified matches.

Preserve the historical day comparison convention: year = 365.2425 days, month = 30.436875, week = 7, day = 1. Record it in the filter plan; it is not calendar-precise age arithmetic. Narrative woman/man/girl/boy labels follow the existing synthetic-topic convention, with explicit abstention for recognized ambiguous sex/gender contexts. This is a research convention, not an inference of biological sex for real people.

Add standalone fixture/TREC extraction and evaluation CLIs requiring explicitly synthetic sources. Cap sources at 2 MiB/200 cases and narratives at 20,000 characters. Reject all malformed/duplicate records together with inspectable positions; do not echo rejected narratives in errors. An asserted synthetic flag is an input contract, not de-identification or proof of synthetic origin.

Integrate profiles into the existing search CLI through explicit `--fact-extractor profile`. Keep `legacy` as default to preserve previous experiments, and keep exact dense plus age/sex as the default retrieval method/filter. `--filter none` must disable demographic application even if a profile is extracted. No existing evaluation silently switches extractor, and hybrid's ranking-promotion gate remains unmet.

## Alternatives and consequences

Do not add a medical language model, terminology service, cloud inference, database schema, search API, or UI now. The rules are reviewable, run with foundation dependencies, and have no model downloads, but intentionally miss unfamiliar concepts and complex context. Full coreference, general clinical NLP, medication doses, and reliable cross-sentence temporal reasoning are not implemented. Future extensions require versioned vocabulary/context rules and new labelled evaluation; fixture accuracy must not be presented as clinical accuracy.

## Validation

Use manually specified synthetic development annotations for full fact-value/span/context/operator metrics and safe-filter outcomes. Report unsupported content separately in an unlabelled 50-topic TREC audit, never as measured accuracy. Test negation scope, relatives/partners/children, uncertain and historical demographics, conflicting evidence, invalid units/overflow, forged profiles, explicit synthetic flags, file boundaries, failed/reused reports, and independence from optional ML packages. Test profile-to-Qdrant behavior in an isolated disposable collection and the real CLI against unchanged legacy results. Reports remain local; reviewed methods and limitations are public.
