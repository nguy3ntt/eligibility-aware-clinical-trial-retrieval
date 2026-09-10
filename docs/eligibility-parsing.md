# Eligibility parsing and bounded criterion search

This workflow structures trial-side eligibility text. It does **not** assess a patient, recommend a trial, or determine eligibility. All patient work remains synthetic-only. Clinical interpretation requires professional review.

## What is implemented

The parser recognizes explicit inclusion/exclusion sections, bullets, numbered/nested lists, blank-line paragraphs, and limited semicolon boundaries. It preserves full decoded source text, original order, exact character spans and parent links. Unknown sections and unsupported wording remain inspectable. Alternatives, exceptions, embedded headings and compound clauses can remain unsplit with review flags.

Types are bounded lexical tags: age, sex, condition, medication, treatment, measurement, consent or other. Numeric extraction supports explicit age, hemoglobin, HbA1c, creatinine, BMI and platelet labels with recognized comparison/range syntax and units. It does not convert units, infer an absent operator, normalize diagnoses, interpret every abbreviation, or resolve complete Boolean logic. `logic` records visible conjunctions; `negation_cues` records wording, not a resolved clinical predicate. For example, “no less than” contains a negation cue but expresses a lower bound.

`parsed-eligibility-v1` retains raw source hashes/field location, a separate decoded-text hash, parser fingerprint, sections and criteria. Artifacts are revalidated and deterministically reparsed when loaded. Missing text produces an explicit empty-text issue, never a satisfied criterion. Invalid sources stop preparation and leave a local failure record.

The separate `criteria_v1` collection contains named dense and sparse vectors plus complete criterion evidence/provenance. The input is section label + ancestor wording + criterion wording. Dense similarity and BM25 scores stay separate. Criterion search currently inspects saved criterion text; arbitrary patient entry, eligibility verification and a search UI are not provided.

## Quick manual checks

Run commands from the Git repository root with the project Python environment active. In the current Windows workspace, the environment is one directory above the Git root, so replace `python` below with `..\.venv\Scripts\python.exe` if it is not activated.

1. Inspect the tiny invented trial. No model or database is needed:

   ```powershell
   python -m pipelines.criteria_parse demo
   ```

   Expect `schema_version: parsed-eligibility-v1`, five criteria in original order, three inclusion criteria and two exclusion criteria, and exact `evidence` text/positions. The age constraint is 18–65 years. `eligibility_assessment` is `not_performed`.

2. Inspect a nested example and run the labelled checks:

   ```powershell
   python -m pipelines.criteria_parse demo --trial-id NCT00000002
   python -m evaluation.criteria --output-id my-criteria-check-01
   ```

   Nested criteria retain `parent_id` and `parent_context_required`. Expected evaluation: `status: passed`, 10/10 exact trials, 27 true positives, zero extra/missed tuples, precision/recall/F1 = 1.0. These are authored development examples, not independently measured clinical accuracy. Use a new output ID for each run; an existing folder is deliberately refused.

3. With the existing local artifacts, start Qdrant if necessary and verify the collection:

   ```powershell
   .\scripts\qdrant-local.ps1 -Action Start
   python -m pipelines.criteria_index verify
   ```

   Expect `status: verified`, 139 criteria, `criterion_dense` and `criterion_sparse`, and six payload indexes. The server is loopback-only. The existing Docker alternative is documented in the [vector storage guide](local-vector-storage.md); do not start two servers on port 6333.

4. Inspect dense and sparse similarity separately:

   ```powershell
   python -m pipelines.criteria_index search --row 1 --method dense --top-k 3
   python -m pipelines.criteria_index search --row 1 --method sparse --top-k 3
   ```

   Expect three ranked criterion results, NCT IDs, section/order, source hashes and field location, exact criterion evidence, review reasons and encoding audit. The dense query is a saved criterion vector; its matching text has cosine near 1. This is a storage/similarity check, not a useful patient search or eligibility probability. Sparse uses the complete saved text and corpus vocabulary. Two long dense inputs are truncated at 256 tokens; `encoding_audit.truncated` exposes this while evidence stays complete.

5. Optional deeper checks:

   ```powershell
   python -m evaluation.criteria --source-id criteria-source-m7-v3 --output-id my-criteria-audit-01
   python -m evaluation.criteria_index --output-id my-criterion-index-check-01
   ```

   The first adds unlabelled coverage counts for 12 trials/139 records. The second re-encodes all records, verifies every payload/vector, compares 32 live queries to independent dense/BM25 calculations and repeats them. Expect `status: passed`. Local results go under ignored `evaluation/reports/<output-id>/`.

## Rebuilding from existing source artifacts

The parser demo and labelled evaluation require the foundation environment (`.[dev]`). Historical preparation/indexing also need the existing `hybrid` extra, verified historical snapshot, bounded dense artifact and pinned MiniLM model. Preparation does not download data or models. Default local inputs are `trec-ct-2021-20210427`, `dense-m3-minilm-v1`, `criteria-source-m7-v3` and `criterion-vectors-m7-v3`.

Use new IDs and a new collection for a new parser/model/artifact contract:

```powershell
python -m pipelines.criteria_parse prepare --limit 12 --output-id criteria-source-rebuild-01
python -m pipelines.criteria_index build --source-id criteria-source-rebuild-01 --output-id criterion-vectors-rebuild-01
python -m pipelines.criteria_index load --index-id criterion-vectors-rebuild-01 --collection criteria_rebuild_01
python -m pipelines.criteria_index verify --index-id criterion-vectors-rebuild-01 --collection criteria_rebuild_01
```

Historical selection takes the first sorted NCT IDs from the existing bounded dense artifact, never a tuned judged subset. Limits are 1–16 trials, 100,000 characters per eligibility field and 1–512 criterion vectors. Excess scope or damaged/incompatible artifacts fail; records are not silently truncated to fit the collection cap. Repeating `load` with the same contract is safe and does not duplicate points. Partial imports can be resumed by repeating the same load. A new contract requires a separate collection; the public CLI never deletes or overwrites an incompatible collection.

The parser has no external service dependency and no stochastic model. The vector artifact records model revision/snapshot, runtime versions, template, token audit, vocabulary statistics and file checksums. Learned embeddings are used only for similarity; the parser is marked `deterministic_rule`.

## Tests and limitations

```powershell
python -m pytest pipelines/tests/test_criteria.py pipelines/tests/test_criteria_index.py
```

Set `QDRANT_TEST_URL=http://127.0.0.1:6333` to include the isolated live criterion test; it creates and deletes only its randomly named test collection. Other tests cover exact source alignment, Windows line endings, nested/compound structures, unsafe quantities, source hashes/CRC/XML identity, artifact corruption, incompatible configuration, empty lexical queries and independent scoring. Optional index tests skip if their ML dependencies are unavailable.

The [reviewed results](experiments/0007-bounded-eligibility-parsing.md) distinguish development contracts from the unlabelled audit. Unrecognized headings, embedded group labels, indirect age wording, uncommon units, alternatives spanning lists and sentence-level clinical interpretation remain limited. No record should be treated as a proven atomic clinical predicate just because it has a type or quantity. Full-corpus/held-out parser validation, patient–criterion verification, reranking and the application interface remain future work.
