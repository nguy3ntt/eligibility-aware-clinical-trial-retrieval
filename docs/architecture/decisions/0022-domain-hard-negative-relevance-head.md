# 0022 — Experimental domain hard negatives with frozen-backbone head adaptation

Date: 2026-10-23. Status: accepted for the requested reranking extension; no promotion.

The user requested domain-specific hard negatives. Existing 2021/2022 cases have already
been inspected. This work therefore uses only the 2022 bounded, judgment-selected pool
and reports a retrospective engineering/development experiment, not a new unseen-case,
full-corpus, clinical or public-model-training-independent result. Original models,
indexes, catalogs, parser/verifier and ordinary search defaults remain untouched.

Partition both synthetic case groups and trial groups using a fixed 60/20/20 group hash.
Near-duplicate word-five-shingle components and exact normalized title/condition keys
provide conservative lexical family proxies. They cannot prove semantic or protocol-family
independence. A labeled pair is usable only when both endpoints belong to the same
partition; cross-partition judgments are recorded as excluded, never relabeled.

Mine confirmed grade-zero negatives among training-only BM25/dense candidates, requiring
condition-term overlap or high dense rank. Preserve source terms, branch ranks/scores and
the reason for selection. Unjudged trials are never negatives. Both source grades one
(excluded but relevant) and two are positive relevance targets with the same pairwise
objective. Screening outcomes never become training labels or ranking features.

Compare equal-budget hard and seeded random negative controls using the same positives.
Freeze the pinned BERT backbone and original bias; train only the 384 classifier weights
from cached, source-linked classifier-input features. This is final-layer adaptation,
not full-model fine-tuning or a claim of newly learned clinical reasoning. Pairwise
softplus loss balances queries and regularizes the weight delta towards the base head.
Parameters are fixed before fitting: seed 0, 20 full-batch Adam steps, learning rate .001,
delta L2 .01. Select among epochs 0/5/10/15/20 using development nDCG@10 only, retaining
the earliest improving checkpoint. Epoch zero can win; do not force an altered model.

Partitioned test-label files cannot be deserialized by fitting. Seal model/control files
before opening test features/labels. Test scoring refuses a missing/changed seal and fresh
destinations prevent overwriting completed attempts. Earlier public label exposure remains
explicit. Save losses, all checkpoint results, input/truncation evidence, family maps,
data/code/model/runtime identities, rankings and exploratory paired intervals.

The adapter is a separate JSON-weight artifact under ignored models storage; no pickle
or replacement of original safetensors is needed. Inference reuses the original pair
template and evidence, returns a separate raw adapted relevance score and original logit,
and preserves candidate membership/tails and deterministic screening blockers.

Expose `reranker_variant: domain_hard` only with explicit reranking, plus an experimental
laboratory selector and case-exposure notice. Missing/incompatible artifacts fail visibly;
there is no training-on-request or fallback. Model identity participates in operation
provenance/replay. Ordinary search stays exact dense, legacy age/sex and no reranking.
No dependencies, paid service, GPU, deployment, staging, commits or pushes are required.
