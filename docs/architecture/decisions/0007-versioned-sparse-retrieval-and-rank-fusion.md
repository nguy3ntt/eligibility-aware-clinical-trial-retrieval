# ADR 0007: Versioned sparse retrieval and auditable rank fusion

- Status: accepted
- Date: 2026-09-05

## Context

The frozen 443-trial diagnostic already supports exact dense retrieval, conservative demographic filtering, and source evidence. A lexical branch must use the same documents and fields to isolate the effect of fusion. Cosine and BM25 scores have incompatible scales. The previously saved full-corpus BM25 baseline remains separate and is not numerically comparable to this judgment-selected pool.

## Decision

Build a separate `trials_hybrid_v1` collection without changing `trials_v1` or its recovery artifacts. Store `overview_dense` and `lexical_sparse` on the same stable trial point. Extend the existing immutable retrieval contract with the lexical parameters, tokenizer package version, vocabulary/document-frequency/document-length hashes, and corpus statistics. Reconstruct lexical state only from the verified ordered dense artifact, never from queries or judgments. Corpus changes require a new artifact and collection, since BM25 statistics are corpus-dependent.

Use the pinned `bm25s==0.3.11` Lucene formulation with `k1=1.2`, `b=0.75`, lowercasing, English stopwords, no stemming, and the existing baseline token pattern. Assign collision-free sparse dimensions by sorted vocabulary. Document weights are `tf / (tf + k1 * (1 - b + b * length / average_length))`; query weights are `query_tf * log(1 + (N - df + 0.5) / (df + 0.5))`. Store float32 weights. This convention has no extra `k1+1` factor, matching the pinned baseline. Disable Qdrant's IDF modifier to prevent applying IDF twice. Store the sparse index in memory, persisted by Qdrant.

Keep the diagnostic bounded to 512 documents. Retrieve exact dense and positive-score sparse matches with identical artifact and age/sex filters. Fetch the bounded corpus before sorting score ties by NCT ID, then retain at most 100 candidates per branch. This avoids arbitrary database cutoff ties; it is not a scalable production search design or latency benchmark. Sparse matches are not padded with unrelated zero-score trials. Empty or out-of-vocabulary lexical queries skip the sparse request; dense retrieval remains available.

Fuse by equal-weight Reciprocal Rank Fusion: sum `1 / (60 + rank)` over the branches that returned a trial, using one-based branch ranks. Fix these parameters before evaluation. Keep each branch's rank, raw score, score type, and RRF contribution with the source payload. Missing branch provenance means absence from that candidate list, not medical exclusion. Reject duplicate branch IDs, nonfinite scores, inconsistent evidence, and mismatched lexical contracts/configuration. Validate existing sparse settings before any collection/index/point mutation.

## Evaluation and consequences

Compare dense, sparse, and hybrid on identical text, queries, candidate depth, and two filter settings. Independently check database scores against direct dense matrix multiplication and the pinned BM25 library, using a separate conservative filter oracle. Save TREC runs, per-topic metrics, result provenance, source/code/model hashes, truncation, and explicit negative findings.

The observed hybrid Recall@100 improves, but mean nDCG@10 falls versus dense in both filter settings. Keep exact dense plus age/sex filtering as the CLI default; hybrid requires explicit selection. Do not tune on this pool and call the result a held-out improvement. No automatic eligibility decision, new infrastructure, API route, or UI is introduced. Only currently reliable age/sex payloads are filtered; richer extraction and criteria remain future work.

Commands are single-writer research workflows. Full readback occurs before search/evaluation and after evaluation; this detects corruption but is not transactional isolation against concurrent mutations. Existing dense-only backup helpers do not verify sparse contents; use hybrid artifact loading into a new named collection plus `verify` for a checked hybrid rebuild. Full-corpus validation, scalable tie handling, hybrid snapshot tooling, and held-out ranking improvement remain future requirements.

## References

- [Qdrant collection creation API](https://api.qdrant.tech/api-reference/collections/create-collection)
- [Qdrant sparse indexing](https://qdrant.tech/documentation/manage-data/indexing/)

