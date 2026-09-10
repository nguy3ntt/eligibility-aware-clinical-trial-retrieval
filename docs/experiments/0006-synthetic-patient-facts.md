# Evidence-backed synthetic patient facts: development evaluation

Date: 2026-09-07. This evaluates a bounded deterministic extraction implementation, not clinical accuracy, eligibility, or an improvement to retrieval ranking. The manually specified fixtures and rules were developed together; there is no held-out test claim.

## Method and evidence

The public fixture `evaluation/data/fixtures/synthetic_patient_facts.json` contains 16 invented cases and 59 manually specified expected fact mentions. Each annotation identifies kind, normalized label/value/unit, exact quote, assertion, temporality, experiencer, and quantity operator. The evaluator compares full tuples including character offsets and certainty; it measures extra and missed facts instead of assuming every extracted mention is correct. Each case also specifies the expected safe demographic filter.

`synthetic-facts-rules-v1` recognizes 26 condition concepts, 16 medication names, six treatment categories, age/sex patterns, and 12 measurement names. It preserves source evidence and abstains from unsupported filter inputs. `profile-demographic-filter-v1` uses only reliable current patient age/sex facts and the existing unknown-preserving Qdrant filter convention. Other facts are not eligibility checks or database filters.

The local final evidence is `evaluation/reports/m6-facts-replay/experiment.json`, with `labelled-results.json` and `unlabelled-topics.json`. The manifest records source/code hashes and Python/Pydantic versions; the fixture SHA-256 is `5802786ac3a2550981262e5b83dfdc1f9e66cc9bb243438a7a300427fffdd5e6`. No commit hash is invented for this uncommitted implementation. Generated profiles and reports remain Git-ignored; only this reviewed narrative and the deliberately small synthetic fixture are public.

## Development results

| Category | Correct facts | Extra | Missed |
|---|---:|---:|---:|
| Age | 10 | 0 | 0 |
| Sex label | 7 | 0 | 0 |
| Condition | 21 | 0 | 0 |
| Medication | 6 | 0 | 0 |
| Treatment | 6 | 0 | 0 |
| Measurement | 9 | 0 | 0 |
| Total | 59 | 0 | 0 |

Exact fact precision, recall, and F1 are 1.0 **on these authored development contracts only**. All 16 cases match their complete annotation set and intended filters. This checks implemented behavior; it does not quantify generalization. The fixture includes negative, uncertain, historical, family/other-person, planned-treatment, unsupported-unit, conflicting-demographic, and no-diagnosis-inference examples.

An additional audit processed all 50 public synthetic TREC topics, preserving 147 recognized facts, 351 clauses with no recognized fact, and 15 unsupported numeric/unit mentions. It supplied age filters for 50 cases and sex filters for 45. These counts are not recall, precision, or evidence of correctness: those topics have no patient-fact gold labels here. Clauses with one recognized fact may still contain unsupported facts; the “unparsed clause” count is not exhaustive missing-information detection.

## Reviewed behavior and limitations

- `demo-context` distinguishes denied asthma/diabetes, possible pneumonia, the mother's historical breast cancer, prior warfarin, and planned surgery. Only current patient demographics constrain retrieval.
- `demo-unknown` does not turn fatigue into a diagnosis, guess an unsupported creatinine unit, or interpret an absent medication list as no medication use.
- `demo-conflict` preserves contradictory ages and narrative sex labels and applies neither demographic filter.
- Synthetic topic 29 retains the explicitly uncertain syndrome wording rather than assigning a diagnosis.
- Topic audit review found partners' sex labels and children's ages being attributed to the patient. Regression fixes recognize those experiencers; tests also cover explicit “the patient is a…” introductions. These were extraction-context corrections, not tuning against relevance judgments.

No symptom-to-diagnosis inference, dose/regimen extraction, comprehensive medical terminology, cross-sentence coreference, calibrated confidence, clinical thresholds, or general temporal reasoning is implemented. “Current” is a local rule classification, not proof of persistence. Exact supported units are required; omitted blood-pressure units stay unsupported. Narrative sex/gender conventions require review and must not be applied to real patients. A synthetic flag is an input declaration, not a privacy detector.

The previous demographic extractor remains the retrieval CLI default. Explicit profile integration is available for dense and hybrid search, but no retrieval improvement claim follows from this extraction evaluation. The hybrid ranking-promotion gate and full-corpus/held-out validation remain open.

## Engineering verification

All 177 publishable tests passed, including four isolated live-server tests; the full local suite passed 191 tests. Lint, formatting, and compilation passed. One existing Starlette/httpx deprecation warning remains. Fact extraction/evaluation also passed a cold-process check with optional ML packages unavailable.

Repeated extraction produced byte-identical labelled profiles and unlabelled topic audits, and final source hashes match the implementation. The rerun `m6-legacy-regression` preserves all six earlier retrieval run files byte for byte and all aggregate metrics. A separate single-query CLI comparison retained the same IDs and payloads with a maximum cosine difference of `3e-8` from the prior batched-query run, below the existing `1e-6` tolerance; exact floating-point equality is not claimed across batch sizes. Manual checks passed four fixture commands, an invalid ID, dense/hybrid profile integration, and disabling filters explicitly.

Reproduction, expected outputs, and isolated live-filter tests are documented in [the operating guide](../patient-facts.md).
