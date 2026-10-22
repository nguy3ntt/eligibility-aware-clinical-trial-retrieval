# Experimental grouped screening and field/passage retrieval

These two opt-in research methods preserve the existing defaults and historical studies.
They use synthetic cases and public trial sources only. Neither confirms medical eligibility.
See [the development results](experiments/0015-grouped-and-passage-methods.md),
[grouped logic decision](architecture/decisions/0020-opt-in-grouped-screening.md) and
[retrieval decision](architecture/decisions/0021-bounded-field-passage-retrieval.md).

## Grouped eligibility logic

The original parser and ordinary v2 screening assessment remain present. A separate
tree represents explicit AND, OR, NOT and scoped conditional/exception requirements.
Each node retains its original criterion IDs, exact source quote/character offsets,
cited synthetic fact IDs, reason, missing information and true/false/unknown predicate.

Examples of the bounded grammar:

| Form | Meaning |
|---|---|
| `(A) AND (B)` | Both predicates are required |
| `Either (A) or (B)` | At least one predicate is required |
| `NOT (A)` | Negation of the entire parenthesized predicate |
| `All of the following:` with indented children | AND group |
| `Any of the following:` / `Either of the following:` | OR group |
| `None of the following:` | NOT of an OR group |
| `If (A), then (B)` in inclusion | B is required when A applies |
| `For female participants: B` in inclusion | Explicit sex-conditioned requirement |
| `Required: (A), unless (B)` in inclusion | B explicitly waives requirement A |
| `Exclude if (A), unless (B)` in exclusion | Exclusion A is explicitly disabled by B |

A/B must themselves be supported expressions: whole age/sex predicates or same-unit
numeric measurements. Recognising an operator does not supply missing clinical knowledge.
The grammar does not understand arbitrary clinical language, disease subtypes, temporal
conditions, medications or unit conversion. Mixed unparenthesized AND/OR, ambiguous bare
`unless`, unrecognised shared headings, preambles and exceptions require review.

Missing facts stay unknown. In an OR group, one true branch is enough; one false branch
alone is not a blocker. In an AND group, a false requirement can establish a blocker
despite other missing facts, provided scope is resolved. Unresolved global scope overrides
section conclusions to unknown; local predicate values remain visible, not trial verdicts.
Entirely inapplicable conditionals do not earn a potential match.

### Manual examples without services/models

From the nested repository with the Python environment activated:

```powershell
python -m pipelines.screening --fixture evaluation/data/fixtures/grouped_screening.json --pair-id group-or-pass --grouped
python -m pipelines.screening --fixture evaluation/data/fixtures/grouped_screening.json --pair-id group-or-unknown --grouped
python -m pipelines.screening --fixture evaluation/data/fixtures/grouped_screening.json --pair-id group-or-fail --grouped
python -m pipelines.screening --fixture evaluation/data/fixtures/grouped_screening.json --pair-id group-waiver --grouped
```

Inspect **`grouped.status`**, not the separate ordinary `screening.status`. Expected:
potential match; insufficient information; likely exclusion; potential match, respectively,
under the invented rule examples. `group-shared-global` stays insufficient information.
The full original text, criteria, facts and ordinary assessment are still included.
These fixtures are not inserted into the API's curated catalog.

```powershell
python -m pytest backend/tests/test_grouped_screening.py -p no:cacheprovider
python -m evaluation.method_extensions grouped --output-id my-grouped-audit-01
```

Use a fresh report ID. The authored fixture contains 30 development contracts, not an
independent test set. The historical audit also needs the preserved local
`screening-coverage-after-v2` evidence packet, which is deliberately absent from GitHub.
No independent human criterion review was performed; no accuracy estimate is earned.

### Browser/API

Start the [prepared workspace](research-workspace.md). Choose `reranking-demo`, open
**Eligibility evidence**, select `NCT90009002`, check **Compare experimental grouped
eligibility logic**, then screen. Expect a separate experimental grouped panel with
a potential-match research status, expandable logic/source details and cited synthetic
facts. The ordinary evidence panel below remains v2. Historical public trials may remain
unknown; this is expected. Toggling the option clears previous results.

API: `POST /v1/screening` with the existing case/trial IDs and `"grouped": true`.
The response retains `result.assessment` and adds `result.grouped`. Repeating an identical
request replays a saved operation explicitly; disabling grouping produces a separate
operation. The experiment dashboard reopens both interpretations without recomputation.

## Separate fields and passages

Explicit preparation creates an additional local artifact, never an overwrite of the
active dense index or Qdrant collection. On this prepared workspace the final artifact
already exists. Verify it rather than rebuilding:

```powershell
python -m pipelines.field_passages verify
python -m pipelines.field_passages search --case-id trec-ct-2022:29
```

Expect 443 verified trials, 443 summary controls, 1,439 whole-field controls and 2,469
passages. All passage inputs fit MiniLM without document truncation. The query retains
the original model limit and reports any truncation; passage retrieval does not fix
long patient queries. Search needs local MiniLM but no running database.

On a fresh prepared source/index installation:

```powershell
python -m pipelines.field_passages build
```

This requires the [existing app source/model preparation](setup.md), reads the verified
443-trial dense and source-evidence artifacts and writes `data/processed/field-passages-v2`.
It takes roughly two minutes on the observed CPU. Never delete a working destination or
edit a manifest to bypass verification. For a new build, use `--output-id <fresh-id>`
and set local `API_PASSAGE_ID` to that identity before restarting the API. Query and
document model/runtime metadata must match. Existing generation v1 is an unused preliminary
build retained for traceability. The current format/algorithm version is `field-passages-v1`.

Passages use original XML field text, 192 tokenizer tokens and 32-token overlap.
Each field selects its best passage per trial; separate field rankings contribute once
each to RRF, constant 60 and branch depth 100. No eligibility text is indexed, no raw
scores from incompatible scales are added, and multiple passages cannot multiply one
field's contribution. More fields and longer text can nevertheless introduce bias;
the current method demonstrably reduces top-ten quality on the development pool.

### Browser comparison

1. Choose synthetic case `trec-ct-2022:29` and open **Retrieval laboratory**.
2. Select **Fields and passages · experimental RRF**. Keep the existing age/sex filter
   and legacy extractor; leave reranking off for the clearest comparison.
3. Click **Run comparison**. Baseline then candidate run sequentially; defaults are unchanged.
4. Expand **Contributing fields and passages** on a candidate result. Inspect the quoted
   passage, XML location/item, character offsets, separate cosine and RRF contribution.
5. Run again and confirm **Saved replay**. Return to **Search workspace** and confirm
   ordinary search still says **No reranking** and **Legacy age / sex**.

API: explicitly choose `"method": "field_passages"` in the existing search request.
The response contains the same catalog contract, separate passage metadata and contributing
segments under each result's ranking branches. Ordinary eligibility assessment is unchanged.
A missing optional artifact fails with `passage_artifact_unavailable`; no request builds
an index or silently falls back to a different algorithm. PostgreSQL and normal API
readiness remain required, even though this experimental ranking uses local exact matrices.

### Fixed development evaluation

```powershell
python -m evaluation.method_extensions retrieval --output-id my-passage-comparison-01
python -m pytest pipelines/tests/test_field_passages.py -p no:cacheprovider
```

The evaluation fixes six methods: BM25 title/conditions, BM25 summary, the unchanged dense
baseline, dense single summary, field fusion and passage fusion. Query encoder/text,
age/sex filters, candidate depth, trial pool and pooled judgments match. It saves full
rankings/branch evidence, per-topic metrics, exploratory paired intervals, truncation,
storage and warm ranking-only timings. Model inputs change intentionally; this is a
representation/aggregation comparison, not a claim about a different encoder.

All 50 2022 cases were previously inspected and the 443 trials were judgment-selected.
These are development metrics, not full-corpus or unseen-case results. Do not retune
this study to manufacture a positive result. The previously evaluated 2021 cases remain
consumed; they are not reused here. Independent new cases/labels and criterion review
would be required before claiming generalised quality or promoting either method.
