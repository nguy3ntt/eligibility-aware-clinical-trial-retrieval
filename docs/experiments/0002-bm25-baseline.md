# Experiment 0002: Frozen-corpus BM25 baseline

- Date: 2026-09-02
- Scope: Milestone 2 lexical retrieval baseline
- Corpus: frozen ClinicalTrials.gov snapshot dated April 27, 2021
- Topics and judgments: 50 synthetic TREC Clinical Trials 2022 topics; 35,394 qrels
- Pipeline versions: `trec-ct-2021-corpus-v1`, `trial-renderer-v1`, `bm25-baseline-v1`
- Selected run: eligibility text representation with conservative age/sex filtering

## Corpus gate

The five official TREC archives were downloaded into an immutable local snapshot. The validator recomputed every archive SHA-256, verified ZIP CRCs and safe paths, parsed every XML record, matched NCT IDs to filenames, rejected duplicates, and checked all judged IDs.

| Gate measure | Result |
|---|---:|
| Valid, unique XML trial records | 375,580 |
| Validation issues | 0 |
| Unique judged trial IDs | 26,585 |
| Judged IDs missing from corpus | 0 |
| Eligibility assessments performed during validation | 0 |

The TREC overview reports 375,581 records, while the delivered archives contain 375,580 XML trials. The fifth ZIP also contains an exact 119-byte `Contents.txt` declaring 375,580 studies. The validator accepts only that checksummed metadata member and records the discrepancy; it does not silently reinterpret arbitrary non-XML files.

The official source does not provide cryptographic checksums. The download manifest pins exact observed byte sizes and server timestamps, and the project records locally computed hashes. This protects reproducibility after acquisition but cannot authenticate the files against a publisher-supplied digest.

## Retrieval method

The renderer produced 375,580 JSONL documents with stable NCT identifiers, archive/member/CRC provenance, original age/sex metadata, deterministic row hashes, and three field representations:

| Representation | Fields |
|---|---|
| `title_conditions` | brief title, official title, conditions |
| `summary` | title fields, conditions, brief and detailed summaries, interventions |
| `eligibility` | summary fields plus original eligibility text |

BM25 used `bm25s 0.3.11`, Lucene scoring, `k1=1.2`, `b=0.75`, lowercase tokens, English stopwords, no stemmer, and a run depth of 1,000. Every representation was run with no filter and with a deterministic age/sex filter.

The filter extracts demographics only from the opening 240 characters of each synthetic case, preventing later mentions of relatives from being mistaken for the patient. It found an age and an unambiguous sex in all 50 topics. A candidate is removed only for an explicit, parseable contradiction. Missing or unparseable trial metadata remains unknown and is retained. This is not criterion parsing and does not establish potential eligibility.

## Results

TREC grades use their source meanings: grade 2 is eligible, grade 1 is excluded, and grade 0 is not relevant. These labels are used only for benchmark scoring and are not fresh medical assessments. nDCG uses linear gain from the source grade.

| Representation | Filter | nDCG@5 | nDCG@10 | MRR | P@10 | R@100 | Success@5 | Grade-2 R@100 | Grade-1 R@100 |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| title + conditions | none | 0.2082 | 0.1882 | 0.4448 | 0.212 | 0.0972 | 0.52 | 0.0988 | 0.0885 |
| title + conditions | age/sex | 0.2363 | 0.2156 | 0.4876 | 0.234 | 0.0979 | 0.62 | 0.1199 | 0.0704 |
| summaries | none | 0.3271 | 0.2824 | 0.6162 | 0.328 | 0.1347 | 0.74 | 0.1422 | 0.1265 |
| summaries | age/sex | 0.3736 | 0.3228 | 0.6746 | 0.340 | 0.1326 | 0.76 | 0.1640 | 0.1058 |
| eligibility text | none | 0.3596 | 0.3447 | 0.6539 | 0.422 | 0.1781 | 0.82 | 0.1760 | 0.1837 |
| eligibility text | age/sex | **0.4079** | **0.3761** | 0.6579 | **0.428** | 0.1770 | **0.84** | **0.2083** | 0.1486 |

Adding more source text improved early ranking in this experiment. The conservative filter improved the selected run's nDCG@10 from 0.3447 to 0.3761 and grade-2 recall at 100 from 0.1760 to 0.2083, while overall recall at 100 changed from 0.1781 to 0.1770 and grade-1 recall fell from 0.1837 to 0.1486. These paired configurations have not received a statistical significance test, so the differences are observations rather than improvement claims.

The selected configuration was chosen by maximum nDCG@10 on these same 50 topics. It is an exploratory baseline selection, not a held-out estimate of generalization.

## Manual error analysis

The five lowest and five highest per-topic nDCG@10 cases from the selected run were manually reviewed against their top ten ranks and source grades. The local worksheet preserves the synthetic case, trial identifiers, ranks, scores, title/condition text, excerpts, qrel provenance, and document provenance.

The strongest topics explicitly named or closely described conditions and procedures that also appeared in trial titles and conditions: Duchenne muscular dystrophy, essential tremor, von Willebrand disease, osteoarthritis, and inguinal hernia repair. Their nDCG@10 values ranged from 0.8234 to 0.9526.

All five weakest topics had nDCG@10 of zero. Cataract, anaphylaxis, and narcolepsy cases were described mainly through findings or symptoms, allowing generic visual-function, pediatric, or sleep terminology to dominate. A Marfan syndrome case and an explicit Down syndrome case also failed because common phenotype, narrative, infant, maternal, and age terms outweighed the more discriminative condition phrase. This identifies lexical term weighting and case-to-condition normalization as concrete limitations for the next dense-retrieval milestone.

## Reproducibility and limits

The selected run, all five comparison runs, per-query metrics, indexes, topic-demographic audit, and reviewed worksheet remain local and Git-ignored. The public repository contains the executable renderer, BM25 runner, metrics, filters, tests, configuration, and this aggregate report, but not the multi-gigabyte corpus or indexes.

Saved input hashes include:

- rendered documents: `a7b133735968d60aa9562bdb8bf8a918345ce7302b12d66393f974cfe80dd84e`;
- official qrels: `e569a531489e03f7b1fab03fe169c8ea66f4a59e8180fa9858b1a6e4bdcb0c5c`;
- official topics: `c5d37709ba14f6cb341b0bea35a7f43bd1cf93647f939659667975229a7abe91`.

The manifest's per-representation `index_seconds` records elapsed wall time for loading, index construction, and both retrieval runs, not pure index-build latency. No latency benchmark, eligibility verifier, diagnosis, treatment recommendation, or current recruitment claim is included. Every result remains a retrieval candidate that requires professional review.

Reproduction commands and storage boundaries are documented in the [pipeline guide](../../pipelines/README.md) and [evaluation guide](../../evaluation/README.md).
