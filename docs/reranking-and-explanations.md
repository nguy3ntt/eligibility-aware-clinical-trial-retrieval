# Bounded reranking and evidence explanations

This optional research workflow reorders a small candidate set for relevance and produces deterministic evidence explanations. It uses public trial text and explicitly synthetic cases only. No score is an eligibility probability. There is no search UI or new API route in this release.

## Behavior and boundaries

The historical search path preserves the current exact MiniLM title/condition retrieval and legacy age/sex filters. It retrieves up to 100 candidates, scores only the first 20 by default, then replaces that prefix order. You can explicitly choose 1–50 candidates. The tail stays in its original order; membership, original scores and ranks are retained. Empty filtered results remain empty. The existing search commands and defaults do not change.

The pinned local cross-encoder sees a synthetic narrative paired with the normalized trial summary: titles, conditions, brief summary, detailed description and interventions. It returns a raw relevance logit, never combined with cosine, BM25 or screening scores. It does not see the trial's eligibility section as a separate verification task. Its model identity, revision, template, input hashes and runtime are recorded.

Inputs are limited to 512 pair tokens: up to 192 query tokens, then the remaining document budget. Both full and retained token counts, truncation flags and character spans are visible under `relevance.ranking.reranker.input`. Document offsets refer to the normalized summary, not raw XML. Original source fields are retained separately under `relevance.fields`, including original text lists and XML locators. Thus a high score never implies that the model read the entire trial or narrative.

Explanations use fixed statements about the recorded ranking operation and existing deterministic screening results. They do not invent a neural rationale, claim token attribution or infer a diagnosis. Full original eligibility text is parsed and screened for the displayed results only. The result includes the full assessment, all criteria in order, section context, patient facts, blockers and missing information. Missing information remains unknown; unsupported public-trial wording often yields insufficient information. NLI advisories do not affect ranking or explanation statements.

Source fields are reconstructed from checksummed historical XML and must reproduce the existing rendered row exactly. Saved screening assessments are reproduced before explanation. Corrupted evidence, mismatched patient/trial identities, incomplete models and unsafe output IDs fail explicitly. Failure reports identify error types without echoing rejected case text.

## Preparation

Run from the nested Git repository. In this workspace, replace `python` with `..\.venv\Scripts\python.exe` if the environment is not activated. The current workspace has its models and evidence already prepared.

For a fresh installation, install `.[dense,hybrid,verification,dev]` and prepare the existing dense artifact using the earlier guides. Then:

```powershell
python -m pipelines.prepare_reranker
python -m pipelines.rerank prepare-evidence
```

Only model preparation downloads public files. Inference is local, CPU, safetensors, with remote code disabled. No case text is uploaded. Repeating model preparation verifies the saved checksums. Evidence preparation reads the immutable historical archives and writes a separate ignored `data/processed/reranking-evidence-v1/` artifact for the existing 443-trial pool. It creates no new criterion index and does not change any database collection. Existing evidence folders are protected: choose a fresh `--evidence-id` to reproduce preparation.

## Manual testing

Start with a quick invented example without loading a model:

```powershell
python -m pipelines.rerank demo --no-rerank
```

Expect three trials, in their authored order:

| Trial | Screening status | Evidence to inspect |
|---|---|---|
| `NCT90009001` | `insufficient_information` | Missing creatinine evidence |
| `NCT90009002` | `potential_match` | Supported age, sex and hemoglobin rules |
| `NCT90009003` | `likely_exclusion` | Supported age contradiction |

These outcomes apply only to the tiny invented rules, not clinical eligibility. The demo order is not a retrieval benchmark and intentionally includes a relevant-but-excluded trial.

Now enable the real model:

```powershell
python -m pipelines.rerank demo
```

Expect an asthma trial to score above the unrelated knee trial. The same three trial IDs and their screening outcomes must remain present regardless of their new positions. Compare `rank`, `original_rank`, the unchanged candidate `score`, and the separate learned `reranker.score`. In particular, relevance must not erase the older-adult trial's age blocker.

Inspect a historical search with an existing synthetic topic:

```powershell
python -m pipelines.rerank search --case-id trec-ct-2022:29 --depth 20 --top-k 3 --output-id my-rerank-search-01
```

This needs the saved local artifacts and models, but no Qdrant server. The output shows three evidence-linked results from the filtered exact-dense candidate set. Review both relevance and screening sections. A returned trial may remain `insufficient_information`; this is expected when full criterion context is unsupported. `--no-rerank` permits a direct comparison with the base candidate order.

For a compact PowerShell view:

```powershell
$result = python -m pipelines.rerank demo | ConvertFrom-Json
$result.results | Select-Object trial_id, eligibility_assessment
$result.results[0].relevance.ranking
$result.results[0].screening.criteria
```

Run the fixed quality/latency diagnostic:

```powershell
python -m evaluation.reranking --output-id my-reranking-check-01
```

This is slower: it processes all 50 synthetic topics, scores depths 10 and 20 twice, and generates source-backed explanations. It compares identical pooled qrels across BM25, exact dense and both reranked prefixes. Expect `status: complete`, 50 topics, identical repeated scores, unchanged candidate membership/tails and `promotion.enabled: false`. Timing varies by machine and other activity. Use a fresh output ID for every run; existing reports are never overwritten. See the [reviewed experiment](experiments/0009-bounded-reranking-and-explanations.md) for measured results, gains and losses.

## Automated checks

```powershell
$env:RUN_RERANKER_TESTS = '1'
python -m pytest backend/tests/test_reranking.py
```

The real-model test runs only when explicitly enabled and never downloads weights. Offline tests cover candidate and evidence boundaries, deterministic explanation outcomes, invalid requests, source tampering and mismatched assessments. Full-project quality checks remain in the contributor instructions.

All raw data, reconstructed evidence, models, reports and temporary files remain ignored. Only code, tests and reviewed operating/experiment documentation are publishable. Private milestone tracking and AGENTS instructions remain local. No Git commit or push is performed by these commands.

The [architecture decision](architecture/decisions/0011-bounded-reranking-and-evidence-explanations.md) records the fixed protocol. Full-corpus/held-out ranking validation, broader clinical-language coverage, dependable semantic screening and application integration remain future work.
