# Evaluation protocol

The project evaluates three different questions separately:

1. Did the system retrieve medically relevant trials?
2. Did it distinguish potentially eligible trials from relevant-but-excluded trials?
3. Did the approximate vector index reproduce exact vector neighbours efficiently?

## Retrieval metrics

- nDCG@5 and nDCG@10
- Precision@10
- Recall@100
- Mean Reciprocal Rank
- Success@5
- eligible-trial recall
- relevant-but-excluded retrieval rate

## Eligibility metrics

- accuracy and macro F1;
- per-class precision and recall;
- high-confidence precision;
- calibration by confidence band;
- criterion-level and trial-level confusion matrices;
- unknown-information accuracy.

## Vector-index metrics

- ANN Recall@10 against exact kNN;
- p50, p95, and p99 query latency;
- index construction time;
- embedding throughput;
- memory and storage consumption.

## Systems to compare

| ID | System |
|---|---|
| B1 | BM25 |
| B2 | dense exact retrieval |
| B3 | dense HNSW retrieval |
| E1 | dense + structured filters |
| E2 | dense + sparse hybrid retrieval |
| E3 | hybrid + reranking |
| E4 | hybrid + reranking + criterion verification |

## Required ablations

- remove dense retrieval;
- remove sparse retrieval;
- remove age and sex filters;
- remove reranking;
- remove criterion vectors;
- remove the learned verifier;
- replace separate representations with concatenated text.

## Experiment manifest

Every run must record:

- code commit;
- data snapshot;
- query and qrels version;
- text fields and rendering template;
- model name and revision;
- embedding dimension and normalization;
- index parameters;
- filter rules;
- fusion and reranking parameters;
- random seed;
- hardware and runtime versions.

## Error analysis

Aggregate metrics are insufficient. Inspect at least:

- terminology mismatch;
- exact identifier failure;
- negation failure;
- temporal misunderstanding;
- missing-patient-information error;
- overly strict or weak filters;
- relevant-but-excluded confusion;
- malformed eligibility text;
- geographic mismatch.

Statistical significance testing should be applied to paired per-query metric values when claiming that one retrieval configuration improves another.
