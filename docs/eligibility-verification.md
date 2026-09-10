# Synthetic research screening

This workflow connects the synthetic patient facts to trial-side criteria. It produces inspectable research outcomes and optional learned text-relation advisories. It does **not** confirm medical eligibility, diagnose, recommend treatment or replace professional review. Retrieval relevance and screening remain separate.

## Supported behavior

`research-screening-v1` includes the complete evidence-backed patient profile and parsed trial, criterion outcomes, rule identity, source/verifier hashes, blocker IDs, unknown-criterion IDs and a missing-information summary. Inputs are freshly re-extracted/reparsed and compared before use. Each criterion remains in original source order.

| Outcome | Meaning in this bounded workflow |
|---|---|
| `satisfied` | Reliable facts satisfy the complete supported inclusion predicate, or show that a supported exclusion predicate is false |
| `violated` | Reliable facts contradict a complete supported inclusion requirement, or make a supported exclusion predicate true |
| `unknown` | Missing, uncertain, conflicting, unanchored, differently measured or unsupported evidence prevents interpretation |
| `not_applicable` | Reliable patient sex makes an explicit supported inline sex condition inapplicable |

Complete age/sex and same-unit numeric predicates are supported. Examples include `Age 18 to 65 years.`, `Male.`, `Hemoglobin >= 10 g/dL.` and `For female participants: Hemoglobin >= 10 g/dL.` Only existing patient-extractor facts are usable. Platelet thresholds can be parsed by the trial parser, but the current patient extractor does not supply platelet facts, so those comparisons abstain.

There is no unit conversion, calendar-age approximation, inference from missing medication/lab history, or choice among conflicting results. Historical, family/other-person, uncertain, approximate and interval-valued facts do not become exact current measurements. Extra timing/visit wording, unresolved preambles, nesting and shared exceptions/alternatives prevent unsupported decisions. Some cues conservatively block all criteria in the trial. This limitation is deliberate and substantially reduces public-trial coverage.

The trial status is `likely_exclusion` when a supported blocker exists; otherwise unresolved requirements produce `insufficient_information`. `potential_match` requires all parsed requirements to have supported satisfied/not-applicable outcomes and at least one satisfied criterion. It means a potential match under the implemented rules, never a full eligibility verdict. Empty trials and entirely not-applicable results stay insufficient-information.

## Manual testing

Run from the Git repository root. In this Windows workspace, use `..\.venv\Scripts\python.exe` in place of `python` below if the environment is not activated. The ordinary screening commands need neither Qdrant nor downloaded models.

```powershell
python -m pipelines.screening --pair-id demo-supported
python -m pipelines.screening --pair-id demo-exclusion
python -m pipelines.screening --pair-id demo-match
python -m pipelines.screening --pair-id demo-not-applicable
```

Expected behavior:

- `demo-supported`: three satisfied requirements and `potential_match`.
- `demo-exclusion`: an age violation, a blocker ID, and `likely_exclusion`.
- `demo-match`: three satisfied requirements but missing creatinine evidence; one unknown, a missing-information entry, and `insufficient_information`.
- `demo-not-applicable`: the explicit female-only measurement requirement does not apply to the invented male case; the criterion is `not_applicable`, but the trial remains `insufficient_information` because no applicable requirement was satisfied.

To view the main fields conveniently in PowerShell:

```powershell
$result = python -m pipelines.screening --pair-id demo-match | ConvertFrom-Json
$result.screening.status
$result.screening.missing_information
$result.screening.criteria | Select-Object outcome, reason, fact_ids
```

Run the authored deterministic evaluation:

```powershell
python -m evaluation.screening --output-id my-screening-check-01
```

Expect `status: passed`, 34 exact pairs, 41 criteria and criterion accuracy 1.0 on these development fixtures. Of the 41 outcomes, 22 are supported decisions and 19 are unknown. Results are authored contracts, not an independent clinical validation. Use a fresh output ID each time; existing output folders are protected.

## Optional local semantic advisory

The optional dependency group is `.[verification]`. The current workspace already has the model and dependencies prepared. On a new installation:

```powershell
pip install -e ".[dev,verification]"
python -m pipelines.prepare_nli
```

Preparation downloads only the pinned public model/tokenizer files into ignored `models/`, records hashes and uses the established Windows long-path handling. Repeating preparation verifies the existing completed snapshot. Interrupted downloads can be resumed; incomplete or corrupted snapshots cannot be loaded as a valid model. No patient text is sent to Hugging Face. Inference is local-only, CPU, safetensors, with remote code disabled.

```powershell
python -m pipelines.screening --pair-id demo-semantic --semantic
```

The deterministic result remains `unknown` / `insufficient_information`. A separate `semantic` object shows raw text-relation probabilities and a proposed outcome with `method: learned_nli` and `promoted: false`. The model may propose `satisfied` for this simple asthma example, but the screening result and blocker list must remain unchanged. Do not interpret softmax values as eligibility probabilities. Pairs exceeding 512 tokens are rejected for advisory scoring, with an explicit reason and token count; no evidence is silently truncated.

Run the semantic diagnostic:

```powershell
python -m evaluation.semantic_screening --output-id my-semantic-check-01
```

This evaluates 24 calibration pairs and 30 disjoint test pairs, fits temperature using only calibration labels, and reports both raw and scaled test metrics. Expected on the recorded environment: test accuracy 0.80, raw high-confidence precision 19/20, selected temperature 3.0, and zero scaled test decisions above the fixed 0.95 threshold. `promotion.enabled` remains false. The scaled test precision is `null` because there are no selected decisions. Calibration is an evaluated experiment, not a silently activated CLI setting.

## Existing synthetic cases and public trial parses

Use the original saved parser artifacts; no criterion or trial index is changed:

```powershell
python -m pipelines.screening --cases evaluation/data/fixtures/synthetic_patient_facts.json --case-id demo-context --source-id criteria-source-m7-v3 --trial-id NCT00000361
```

Expect source evidence and `insufficient_information`, not a forced decision. `--topics <saved-topics2022.xml> --case-id trec-ct-2022:<id>` also accepts the existing synthetic TREC source. There is no arbitrary real-patient input endpoint. The synthetic flag is a source contract, not a privacy detector; never provide real identifiable patient information.

```powershell
python -m evaluation.screening --cases evaluation/data/fixtures/synthetic_patient_facts.json --source-id criteria-source-m7-v3 --output-id my-screening-audit-01
```

This audits the 16 synthetic profiles against 12 public trial parses: 192 pairs and 2,224 criterion assessments. All currently abstain because the bounded rules cannot safely resolve the complex source text. This is a coverage result, **not** evidence that the patients are eligible, excluded or medically unmatched. The audit caps work at 200 pairs and retains every assessment locally.

## Automated checks and files

```powershell
python -m pytest backend/tests/test_screening.py evaluation/tests/test_semantic_screening.py
```

Set `RUN_NLI_TESTS=1` to run the real pinned-model test, including repeat inference, negation and token-limit abstention. The foundation rules and their tests do not require ML packages. The optional semantic tests skip when NumPy is unavailable; no test automatically downloads a model. Existing database tests use their separate `QDRANT_TEST_URL` setting and need the local server running.

Add `--output-id <fresh-id>` to the screening CLI to retain its full evidence packet under ignored `evaluation/reports/`. Evaluations always require a new report ID. Reports record inputs, outcomes, code/model/fixture identities, detailed predictions and declared limitations. Agent instructions, the milestone tracker, models, generated reports, raw/derived data and scratch files stay excluded from Git.

See [ADR 0010](architecture/decisions/0010-evidence-backed-screening-and-nli-advisories.md) and the [reviewed results](experiments/0008-bounded-screening-and-semantic-verification.md). Broader independently validated criterion coverage, reliable semantic screening, full-corpus validation, reranking and the application interface remain outside this bounded implementation.
