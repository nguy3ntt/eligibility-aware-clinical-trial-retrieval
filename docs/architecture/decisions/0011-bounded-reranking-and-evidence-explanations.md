# ADR 0011: Bounded relevance reranking and deterministic evidence explanations

Date: 2026-09-10. Status: accepted for a bounded research workflow.

## Context

Retrieval relevance, deterministic eligibility screening and learned NLI advisories have distinct meanings. A reranker must not combine their incompatible scores or turn missing information into a medical conclusion. The existing 443-trial diagnostic is judgment-selected, not held out.

## Decision

Use the public `cross-encoder/ms-marco-MiniLM-L6-v2` model at revision `233902d25c440f23af6f7d6e94d2946bac0bee0a`, loaded locally with safetensors and remote code disabled. It scores a synthetic narrative paired with the normalized trial summary. The [official model card](https://huggingface.co/cross-encoder/ms-marco-MiniLM-L6-v2/tree/233902d25c440f23af6f7d6e94d2946bac0bee0a) describes a general passage relevance model, not a clinical eligibility model.

Before scoring the diagnostic, fix candidate depths 10 and 20; retain the same exact dense top-100 and legacy age/sex filters. A CLI safety cap permits at most 50 scored candidates. Sort each scored prefix by raw relevance logit and trial ID, retaining the unscored tail unchanged. Never add dense, BM25, reranker or eligibility scores. Preserve original scores/ranks. Do not change default retrieval based on this non-held-out diagnostic.

Fix CPU execution to four threads, batch size eight, seed zero and a 512-token pair limit. Keep at most 192 query tokens; allocate the remaining pair budget to the summary. Store exact token counts, retained character spans and input hashes for both sides, exposing every truncation. These offsets refer to the normalized summary; original XML field text and locators are retained separately. Full eligibility source is never truncated for deterministic screening.

Reconstruct source fields from immutable checksummed historical XML and require that they reproduce the saved renderer rows. This separate bounded evidence artifact holds no criterion vectors and changes no prior index. Explain results with fixed templates and validated stored facts, source fields and whole-criterion assessments. Reproduce screening packets before explaining them; reject patient/trial or source mismatches. Never claim token attribution or invent a reason why a neural score was high. NLI advisories are not used in ranking or generated explanation statements.

Measure BM25, exact dense and reranked prefixes on identical pooled qrels. Preserve per-query gains/losses, top-result judgments, truncation and all candidate sets. Measure warm repeated reranking at both depths separately from model/artifact loading, query encoding, base ranking and explanation work. Replay scores/rankings; timing naturally varies. Quality improvement is a measured outcome, not a required positive result. No threshold, depth, model or dataset selection may be retuned to manufacture improvement.

## Consequences

The result is an optional command-line research path. Existing retrieval defaults, API routes, indexes and semantic non-promotion remain unchanged. General-domain model limitations, incomplete judgments, summary truncation, limited screening coverage and lack of held-out/full-corpus validation remain explicit. A later API/UI milestone can reuse the evidence contracts; deployment and automatic eligibility decisions are out of scope.
