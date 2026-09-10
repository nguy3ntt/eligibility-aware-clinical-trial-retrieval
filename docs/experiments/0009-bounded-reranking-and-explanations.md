# Bounded reranking and source-backed explanations

Date: 2026-09-10. **The implementation works, but this reranker reduces average ranking quality and adds latency on the frozen diagnostic. Exact dense plus legacy age/sex remains the default.** No clinical screening improvement, full-corpus benefit or held-out generalization is claimed.

## Fixed protocol

Use the existing 443 historical trials, all 50 synthetic TREC 2022 topics and 1,511 pooled judgments from the 35,394 source judgments. The pool was selected using judgments in earlier work; it is not held out. Missing judgments receive zero gain for evaluation, not a claim of irrelevance. Source grades are benchmark labels, never new medical assessments. The full-corpus BM25 baseline remains separate and is not directly comparable with these pooled metrics.

The dense artifact remains `dense-m3-minilm-v1`, manifest SHA-256 `f66e32d568983d2061db23a92e2d781f8f46f69030f965cf901c4623792f7480`. Reconstruct original fields from the checksummed historical XML into `reranking-evidence-v1`; all 443 original rows reproduce exactly. Evidence-file SHA-256 is `099dd17cee2ba35f95831ad99de6918282160b79352230d949fbadf8612f3c5b`. This creates no vector index and changes no earlier artifact.

BM25 and exact MiniLM dense use the same legacy age/sex filters and title/condition representation as the earlier diagnostic. Their aggregate metrics reproduce the earlier filtered results. The reranker sees each synthetic narrative paired with the normalized summary representation: titles, conditions, summary, detailed description and interventions. Model: `cross-encoder/ms-marco-MiniLM-L6-v2`, pinned revision `233902d25c440f23af6f7d6e94d2946bac0bee0a`. The [primary model card](https://huggingface.co/cross-encoder/ms-marco-MiniLM-L6-v2/tree/233902d25c440f23af6f7d6e94d2946bac0bee0a) describes a general passage-relevance model; it is not a clinically validated verifier.

Depths 10 and 20 were fixed in [ADR 0011](../architecture/decisions/0011-bounded-reranking-and-evidence-explanations.md) before diagnostic scoring. Both reorder only their prefix of the same dense top-100; all tail positions and candidate membership remain unchanged. Raw logits and original cosine scores stay separate. No model, threshold, pool or depth was retuned after observing losses. The CLI cap is 50 candidates; research default depth 20 does not change existing retrieval defaults.

Inference is local CPU, four threads, batch size eight, seed zero, 512 pair tokens, with up to 192 query tokens and the remaining document budget. The model uses safetensors with remote code disabled. Explicit token counts, shortened input spans and input hashes are saved alongside the full source evidence. Screening uses full original eligibility text, never truncated model passages.

## Quality results

Higher values are better; these are relevance metrics, not medical eligibility rates.

| System | nDCG@10 | Precision@10 | MRR | Recall@100 |
|---|---:|---:|---:|---:|
| BM25, age/sex | 0.3823 | 0.2620 | 0.6321 | 0.6217 |
| Exact dense, age/sex | 0.5584 | 0.3720 | 0.8035 | 0.7518 |
| Dense + rerank 10 | 0.5368 | 0.3720 | 0.7675 | 0.7518 |
| Dense + rerank 20 | 0.4956 | 0.3500 | 0.7215 | 0.7518 |

Depth 10 loses 0.02160 mean nDCG@10, with 19 topic wins, 27 losses and four ties. Its Precision@10 cannot change because the same ten documents are only reordered. Depth 20 loses 0.06274 mean nDCG@10, with 16 wins, 33 losses and one tie. Recall@100 cannot improve under either prefix reorder because candidate membership is unchanged. No significance or generalization claim is made from this selected pool.

Examples from preserved rankings and source judgments:

- Topic 21 gains 0.35464 nDCG@10 at depth 20: `NCT03536962`, source grade 2, moves from dense rank 15 to rank 1. This is the largest observed gain, not a reason to promote the model.
- Topic 8 loses 0.51670: the dense first result `NCT02857205` is source grade 2, while the reranker promotes unjudged `NCT01234883` to first and unjudged `NCT02415361` from dense rank 14 to third. Unjudged does not prove medical irrelevance.
- Topic 3 loses 0.48008: the original first two results have source grade 2, while unjudged `NCT00254553` moves from dense rank 16 to first. Grade-1 results take second and third. These movements describe evaluation behavior, not causal claims about model reasoning.

## Timing and input coverage

Both models are warmed before measurement. Every topic/depth is scored twice; depth order alternates between topics. Timings exclude model loading and source-artifact verification and are saved separately from deterministic predictions. They measure local CPU work, not HTTP service latency or a production benchmark.

The final release run measured median added reranking time of 0.502 seconds at depth 10 (p95 0.683) and 0.997 seconds at depth 20 (p95 1.351), from 100 timed calls per depth. Median dense query encoding plus exact candidate selection was 0.021 seconds; explaining three results took 0.033 seconds. Model/artifact loading took 5.27 seconds. The initial run had medians of 0.640/1.291 seconds for the two depths, illustrating local timing variability; timings are not replay-identical.

One of 50 queries is shortened at the reranker's query cap, affecting 10/500 scored pairs at depth 10 and 20/1,000 at depth 20. Summary inputs are shortened for 247/500 pairs at depth 10 and 541/1,000 at depth 20. Full original field text remains available; the relevance model has not read all that evidence. The inherited dense encoder also truncates one query. These are coverage limitations and are not hidden by explanations.

## Explanations and safety

For each topic, the top three depth-20 results receive deterministic source-linked explanations: 150 patient–trial packets with 1,782 criterion records. All 150 trial summaries are `insufficient_information`. This is an unlabelled coverage observation, not evidence that the cases are eligible, excluded or medically unmatched. The broader Milestone 8 screening gap remains unresolved.

Every displayed result includes original trial field text and XML locators, archive/member provenance, XML and rendered-row hashes, the synthetic source identity, original/final ranks, separate scores and actual reranker input spans. Criterion explanations retain full screening packets with original eligibility text, section/ancestor context, exact spans, patient facts, blockers, missing information and rule fingerprints. Stored assessments are reproduced before explanation. Templates never invent a neural rationale or turn a relevance logit into an eligibility probability. NLI advisories are not used.

The invented demo deliberately retains three distinct statuses. A highly ranked asthma trial can still carry an age blocker and `likely_exclusion`; another tiny supported example is `potential_match`, and missing creatinine evidence produces `insufficient_information`. Those outcomes remain attached to the same trial IDs after reranking. They are research contracts, not clinical validation.

## Verification and reproducibility

All 351 local and 337 publishable tests passed, including five live Qdrant tests, the real NLI test and the real reranker test. The 38 new tests cover candidate/tail preservation, stable ties, score bounds, normal-tokenizer agreement, real relevance/replay/truncation, invalid requests, field/input/assessment tampering, cross-case/trial mismatches and protected output folders. Ruff lint/format and compilation passed. Eight existing upstream warnings remain visible: one Starlette/httpx deprecation and seven DeBERTa/PyTorch deprecations.

The first real-model test exposed a tokenizer API compatibility issue. The implementation now constructs the pinned BERT pair template explicitly and tests its scores against the tokenizer's ordinary untruncated pair encoding. Demo criteria use explicit bullets to match the existing parser's conservative clause boundary contract; ambiguous line breaks are not reinterpreted as independent predicates. Windows sandbox restrictions on temporary folders, formatter writes and network downloads were resolved through approved tool access, not permission workarounds.

All nine manual checks passed: invented base/reranked outputs, historical base/reranked search, protected report reuse, invalid depth, unsafe output ID, missing synthetic case and offline model snapshot verification. The existing server was started for regression checks; dense and hybrid collections each still verify 443 points, and the criterion collection still verifies 139 records. No infrastructure definition or prior retrieval default changed.

Machine-readable evidence remains ignored under `evaluation/reports/m9-reranking-release/`; `m9-reranking-initial/` records the first complete run before additional validation hardening. Reports retain full rankings, explanations, error analysis, metrics, 23 implementation fingerprints, model/input identities and timing boundaries. Manual evidence is in `m9-manual-checks.json` and the four `m9-manual-*` folders. No fictitious commit identifier is recorded: all existing uncommitted work remains preserved, and nothing was committed or pushed.

The release rerun produced byte-identical `predictions.json`, `explanations.json` and `error-analysis.json` compared with the initial run, and all metrics were exactly equal. The release's 23 implementation fingerprints match the final code. Prediction SHA-256: `a9a7c6e21f0014a0755fde294d7c3bb89d5966512be9306620f0882b2325f919`; explanation SHA-256: `1b34235f49bd086bfc92837ba2c5e2280792bd9b1945ad40df54bf7a58c681cc`. Experiment manifests intentionally differ in code identity after validation hardening; timing files are separate and vary.

Bounded engineering completion does not satisfy a ranking-promotion or clinical-validation gate. Exact dense plus age/sex and the legacy extractor remain defaults; hybrid and NLI promotion remain unmet. API/persistence integration is a later milestone. The [operating guide](../reranking-and-explanations.md) gives reproducible manual commands and expected behavior.
