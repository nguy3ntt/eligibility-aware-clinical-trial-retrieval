# Synthetic patient fact extraction

The current command-line workflow turns explicitly synthetic narratives into auditable fact mentions and an optional age/sex filter plan. It does not decide medical eligibility, infer diagnoses, or recommend treatment. No graphical interface or search API is available yet.

## What is extracted

| Category | Supported initial behavior |
|---|---|
| Age | Numeric day/week/month/year `old` expressions and compact `63F`/`70M` introductions; only anchored current patient values may filter |
| Sex label | Explicit male/female and narrative woman/man/girl/boy/lady/gentleman labels; no pronoun inference; recognized ambiguity requires review |
| Conditions | 26 project concepts, including diabetes, asthma, hypertension, selected cancers, and cauda equina syndrome |
| Medications | 16 names, including metformin, insulin, aspirin, warfarin, and selected other drugs; no dose/regimen inference |
| Treatments | Chemotherapy, radiotherapy, immunotherapy, dialysis, surgery, and specified organ/bone-marrow transplant wording |
| Measurements | Hemoglobin, HbA1c, creatinine, glucose, weight, height, temperature, pulse, oxygen saturation, BMI, and systolic/diastolic blood pressure; explicit supported units required |

The complete bounded vocabulary and aliases live in `backend/app/services/patient_extraction/rules.py`. Unsupported wording remains in the original narrative. `coverage: bounded_rules_not_exhaustive` is intentional: a profile is not a complete medical record. `missing_categories` means no recognized mention of that category, not proof that the patient lacks it; family/history/uncertain mentions remain distinguishable in each fact. A clause containing one recognized fact can still contain unsupported information.

Each fact includes the canonical project label/value, original quote and offsets, containing context, deterministic rule identity, assertion, certainty, temporality, and experiencer. `asserted` describes the source wording and is not model confidence. `current` means no supported historical/planned cue was recognized; this heuristic can be wrong in complex prose. `historical` does not imply that a disease has resolved, and `absent` is a negated mention rather than independently verified absence. Do not perform clinical screening from these labels.

## Try the local examples

Run from the repository root in the project Python environment. Foundation dependencies suffice (`pip install -e ".[dev]"`); extraction and its labelled evaluation require no Qdrant, models, internet, or ML extras. In the existing Windows workspace, use `..\.venv\Scripts\python.exe` instead of `python` if the environment is not activated.

```bash
python -m pipelines.patient_facts --cases evaluation/data/fixtures/synthetic_patient_facts.json --case-id demo-current
python -m pipelines.patient_facts --cases evaluation/data/fixtures/synthetic_patient_facts.json --case-id demo-context
python -m pipelines.patient_facts --cases evaluation/data/fixtures/synthetic_patient_facts.json --case-id demo-unknown
python -m pipelines.patient_facts --cases evaluation/data/fixtures/synthetic_patient_facts.json --case-id demo-conflict
```

Expected: `status: complete`, a `profile`, and a `filter_plan`.

- `demo-current`: age 52, narrative Male, type 2 diabetes, metformin, hemoglobin, two blood-pressure values, and planned chemotherapy. Age/sex filters apply.
- `demo-context`: asthma and diabetes are absent mentions; pneumonia is uncertain; breast cancer belongs to the mother and is historical; warfarin is historical; surgery is planned. Only the patient's current age/sex constrain retrieval.
- `demo-unknown`: no supported facts, inspectable unsupported-unit/unparsed-clause issues, and no demographic filters. Missing data never become satisfied criteria.
- `demo-conflict`: conflicting ages and sex labels remain preserved, and the filter plan abstains rather than choosing a value.

Quotes use zero-based, end-exclusive Python character offsets into `profile.case.text`. Check `text[start:end]` against the stored quote without trimming or normalizing the narrative. The enclosing `context` retains cues such as “denies,” “possible,” “mother,” or “previously.” Look at `filter_plan.decisions` for `apply`/`abstain`, the reason, and supporting fact IDs. Conditions, drugs, treatments, and measurements are explicitly non-filtering at this stage.

## Use a saved synthetic topic

```bash
python -m pipelines.patient_facts --topics data/raw/m1-20260831-500-v2/topics2022.xml --case-id trec-ct-2022:29
```

The existing topic 29 should contain age/sex mentions, constipation, and an **uncertain** cauda equina syndrome mention with exact evidence. This reflects the supplied synthetic wording; the extractor does not diagnose that syndrome. Use the full case ID (`trec-ct-2022:29`), whereas the search CLI still uses numeric `--topic-id 29`.

For another locally invented fixture, follow the provided `synthetic-cases-v1` JSON envelope with a dataset ID, literal `synthetic: true`, and unique `case_id`/`text` rows. Do not paste real patient information. The flag is not a de-identification tool. Invalid or duplicate rows fail the whole load; structured failure output reports safe record positions without echoing rejected narratives. Keep custom cases under an ignored directory such as `tmp/`.

## Optional integration with existing retrieval

Start the already prepared local Qdrant service and ensure the hybrid collection/model artifact from the [hybrid guide](hybrid-retrieval.md) exists. On this Windows workspace: `scripts/qdrant-local.ps1 -Action Start`.

```bash
python -m pipelines.hybrid_index search --topics data/raw/m1-20260831-500-v2/topics2022.xml --topic-id 29 --fact-extractor profile --method dense
python -m pipelines.hybrid_index search --topics data/raw/m1-20260831-500-v2/topics2022.xml --topic-id 29 --fact-extractor profile --method hybrid
```

Expected: the usual potential matches plus `patient_profile`, `profile_filter_plan`, and `profile_filters_applied: true`. `filter_facts` must equal the profile plan's demographics. Add `--filter none` and expect `profile_filters_applied: false` and `filter_facts: null`; the profile is still shown for inspection.

Omitting `--fact-extractor profile` retains the legacy extractor so earlier retrieval experiments remain reproducible. Omitting `--method` retains dense search. No previous ranking-quality conclusion is changed by the new extractor. It can abstain more often than the baseline and has not been shown to improve retrieval relevance.

## Run evaluation and tests

```bash
python -m evaluation.patient_facts --topics data/raw/m1-20260831-500-v2/topics2022.xml --output-id facts-manual-01
python -m pytest backend/tests/test_patient_facts.py
```

Use a fresh output ID on every evaluation; omit `--topics` to run only the self-contained development fixture. Expected labelled result: 16 exact cases, 59 correct facts, zero extra/missed facts, and 16 correct filter cases. The optional audit processes 50 unlabelled topics; its counts are coverage observations, **not** an accuracy score. Read `labelled-results.json` for full errors/profiles, `unlabelled-topics.json` for unsupported content, and `experiment.json` for metrics and hashes. Failed evaluations preserve a failure report; an existing output directory is never overwritten.

The live integration test is opt-in: set `QDRANT_TEST_URL=http://127.0.0.1:6333` before pytest. It verifies known age/sex contradictions and preservation of unknown trial metadata in its own randomly named collection. All fixture-only tests work without the server; the live test skips if the environment variable is absent.

See [the reviewed evaluation](experiments/0006-synthetic-patient-facts.md) for limitations. Perfect scores on these authored development examples do not establish held-out or clinical performance. Future work must expand labelled data and vocabulary, test more complex context, and keep raw evidence available for professional review.
