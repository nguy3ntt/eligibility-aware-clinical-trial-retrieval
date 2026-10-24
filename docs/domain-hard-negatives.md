# Domain-specific hard-negative reranking

This opt-in experiment tests whether difficult, externally judged irrelevant trials can
improve relevance reranking. It trains only the original cross-encoder's 384 final
classifier weights; BERT and the bias stay frozen. It is not full-model fine-tuning or
an eligibility classifier. Ordinary search remains exact dense, legacy age/sex filtering
and no reranking.

**Result:** both the hard-negative model and matched random-negative control selected
epoch zero. Training reduced pair loss but did not improve development nDCG@10. The
selected artifact therefore retains the original head. This is a completed negative
experiment, not a demonstrated ranking improvement. See the
[reviewed experiment](experiments/0016-domain-hard-negative-reranking.md) and
[architectural decision](architecture/decisions/0022-domain-hard-negative-relevance-head.md).

## How the experiment works

1. Freeze the protocol, original sources and lexical case/trial group split before mining.
   Case groups and trial groups each belong to one train/development/test partition.
   Only judgments whose two endpoints share a partition are usable.
2. Mine training negatives from BM25/dense candidates. A hard negative must have an
   external grade-zero judgment and either source-condition word overlap with the
   synthetic narrative or a high dense rank. Never treat an unjudged trial as negative.
   Grade-one relevant-but-excluded trials remain positive relevance examples alongside
   grade two; deterministic eligibility outcomes never supply relevance labels.
3. Compare a seeded random-negative control using the same positive examples and pair
   budget. Fit a query-balanced pairwise loss on frozen classifier-input features.
4. Select among fixed checkpoints using development nDCG@10, keeping the earliest
   checkpoint on ties. Seal model/control/feature files before opening test labels.
5. Rerank only the first 20 dense candidates, retaining the rest of each candidate list.
   Save every ranking, original logit, source span, per-case metric and exploratory
   paired interval. Reproduce training and metrics from the sealed features.

The split is retrospective: all 50 TREC 2022 topics and the 443 judgment-selected trials
were inspected in earlier development. Lexical groups are duplicate proxies, not proof
of semantic, protocol-family or public model-training independence. No 2021 case is
reused, no threshold is retuned after results, and no new unseen-case claim is earned.

## Local preparation and verification

Use the existing Python environment with the dense, hybrid and verification dependencies,
the verified `dense-m3-minilm-v1` and `reranking-evidence-v1` artifacts, original 2022
topics/qrels, and pinned local MiniLM embedding/cross-encoder snapshots. Nothing below
downloads a model or changes a database/index. Models, mined data and reports stay ignored.

The prepared artifacts in this workspace can be checked from the repository root:

```powershell
..\.venv\Scripts\python.exe -m pipelines.hard_negatives verify
..\.venv\Scripts\python.exe -m pipelines.train_domain_reranker verify
..\.venv\Scripts\python.exe -m evaluation.domain_hard_negatives
```

Expect verified status, selected epoch zero, `promoted: false`, two reproduced training
controls and 32 reproduced test rankings. The final command loads the pinned model head
and reruns the cheap optimizer on cached features; it does not rerun transformer inference
or overwrite the study. Identity, inventory, feature, chronology or metric mismatch fails
closed. Strict code/runtime binding means historical studies need their frozen source
and matching runtime after future implementation changes.

To reproduce preparation/training/scoring, use new output identities. Existing directories
are deliberately rejected; do not delete or overwrite historical artifacts:

```powershell
..\.venv\Scripts\python.exe -m pipelines.hard_negatives prepare --data-id domain-hard-negatives-repro-v1
..\.venv\Scripts\python.exe -m pipelines.train_domain_reranker fit --data-id domain-hard-negatives-repro-v1 --model-id domain-hard-reranker-repro-v1 --study-id domain-hard-reranker-repro-v1
..\.venv\Scripts\python.exe -m pipelines.train_domain_reranker score-test --data-id domain-hard-negatives-repro-v1 --model-id domain-hard-reranker-repro-v1 --study-id domain-hard-reranker-repro-v1
..\.venv\Scripts\python.exe -m evaluation.domain_hard_negatives --data-id domain-hard-negatives-repro-v1 --model-id domain-hard-reranker-repro-v1 --study-id domain-hard-reranker-repro-v1
```

Timestamps and timing differ; on the same verified source/runtime the deterministic
training values, selected checkpoints and rankings should reproduce. These commands
are experiments, not app startup requirements.

## Manual browser testing

Start the existing local stack using the [workspace guide](research-workspace.md), then
open <http://127.0.0.1:5173>. The default adapter is the separate local
`models/domain-hard-reranker-v1`; `API_DOMAIN_RERANKER_ID` can select another prepared
artifact. Missing optional weights yield a structured 503 error, never automatic training.

1. Select synthetic case **29**, then open the **Retrieval laboratory**.
2. Keep the candidate method **Dense**, enable reranking and select
   **Domain hard-negative head · experimental**. Run the comparison.
3. Check that the result explicitly states the recorded case exposure, **NOT PROMOTED**,
   and that development selection retained the original head at **epoch 0**. This is
   expected, not a failed request. Baseline and candidate keep separate score scales.
4. Inspect result details: source evidence and original retrieval ranks remain available;
   reranker logits are relevance scores, not match percentages or eligibility judgments.
5. Open the saved operation again. It must be identified as historical replay and retain
   the experimental model identity and evidence without rerunning training.
6. Disable reranking: the model selector resets to the original model. Return to ordinary
   Search and run the case; it must still report no reranking.

The API equivalent is a search request with `rerank: true` and
`reranker_variant: "domain_hard"`. The default is `"base"`; requesting the domain variant
without reranking is rejected with 422. Adapter hashes enter operation identities, so
different models cannot silently reuse the same saved result. Existing base-model
historical packets remain readable.

## What remains unproven

The tiny disjoint evaluation partition has eight cases and 89 trials; two cases have no
judged relevant trial and remain in the average. It is a bounded diagnostic, not full-corpus
evaluation, independent validation or clinical accuracy. A future full-backbone adaptation
would need a separately scoped training budget, richer independently curated data and a
new sealed evaluation design. This result does not justify changing any search default.
