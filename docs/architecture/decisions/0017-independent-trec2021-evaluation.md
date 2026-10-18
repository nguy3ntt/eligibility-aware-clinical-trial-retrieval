# 0017 — Sealed evaluation on externally judged TREC 2021 cases

Date: 2026-10-18. Status: accepted for the requested independent-evaluation extension.

## Context

All 50 TREC 2022 cases have been inspected during development. Repeating those results
cannot establish performance on unseen project cases. TREC 2021 provides a separate
synthetic case set and externally produced graded judgments over the same April 27,
2021 trial snapshot. Source pages: [track](https://www.trec-cds.org/2021.html) and
[NIST judgments](https://trec.nist.gov/data/trials2021.html). The track describes assessment
by physicians trained in medical informatics. Grades 0/1/2 mean not relevant/excluded/eligible
in the source benchmark; they are not fresh medical assessments by this application.

## Decision

Add an isolated `evaluation.independent` command with write-once stages:

1. **Freeze** code hashes, package/runtime versions, Git base identity and dirty status,
   full-corpus render/index identities, pinned model snapshot identities, source URLs,
   all comparison settings and interpretation before acquiring 2021 cases.
2. **Acquire topics** through the existing bounded HTTP snapshot connector. Preserve
   raw bytes and source metadata in a new ignored `data/raw/` snapshot. Parse 2021 into
   its own namespace; leave the application's strict 2022 loader unchanged.
3. **Audit overlap** before labels, using casefolded word normalization and character
   5-gram Jaccard against every 2022 development narrative. Reject at 0.8 or above;
   reject duplicate normalized narratives within 2021. Stop rather than silently remove
   difficult or overlapping cases. This is a lexical gate, not semantic independence proof.
4. **Rank and seal** every new case over the verified 375,580-trial corpus. Require the
   existing document/query runtime contract and an independent blocked exact-score check.
   Save all raw scores, branch ranks, reranker evidence, input truncation and depth-100
   runs. Seal their byte hashes before any judgment acquisition. Run-file scores are
   monotonic rank surrogates, preserving the actual ranking; original scales stay in JSON.
5. **Acquire external judgments** only with an intact seal. Validate every label and
   join, reject duplicates, require judgments for every topic and corpus coverage of every
   judged trial. No generated or self-assigned relevance labels are allowed.
6. **Score once** using the established metrics. Retain all per-topic results, negative
   findings, judged fraction at 10, and paired uncertainty. Verify hashes on reopening.

Keep existing methods and parameters: matched title/condition Lucene BM25 k1=1.2,
b=0.75; exact normalized MiniLM; RRF with equal branches, constant 60 and branch depth
100; hybrid reranking depths 10 and 20. Apply the existing legacy age/sex filter to all
five systems. Summary inputs give reranking additional text; disclose the confound.
No tuning, default change or automatic model promotion follows this evaluation.

Prespecify **dense versus matched BM25 nDCG@10** as the one primary comparison.
Hybrid and rerank-10/20 versus dense are secondary exploratory contrasts with no
multiplicity adjustment. Use seeded paired-topic percentile bootstrap intervals with
10,000 resamples. MRR is truncated at 100. Preserve source-grade metrics and pooled
unjudged-as-zero-gain semantics, alongside judgment coverage.

## Independence and limits

This is a holdout from this project's recorded configuration development, with external
historical judgments. Public cases may occur in pretrained-model data; that overlap is
unknown. Lexical checks cannot certify semantic disjointness. Cases will have been
consumed after this run, so subsequent tuning on them makes them development evidence.

Local timestamp/hash sequencing is auditable provenance, not externally registered
preregistration, cryptographic authentication, or adversarial access control. A trusted
operator could replace local records. Existing corpus and model artifacts are reused;
this is not a new-corpus or new-model experiment. It does not provide independent
criterion-level labels, clinical validation or an unbiased modern-registry benchmark.

## Consequences

The API, active indexes, synthetic catalog and UI retain their current behavior. The
new work uses offline evaluation and existing model weights, without new infrastructure.
Raw cases, judgments, ranked evidence and protocols remain ignored; publish only source,
reviewed aggregate results and reproducible commands. The owner handles GitHub commits.
