# ADR 0004: Pin local dense encoders and validate exact search before scaling

- Status: accepted
- Date: 2026-09-03

## Context

The frozen corpus and full-corpus BM25 baseline are available. Dense retrieval must now be tested without confusing semantic similarity with clinical eligibility. Encoding every trial before validating the model interface, document alignment, truncation, and search math would create expensive artifacts with uncertain correctness.

## Decision

Start with a deterministic sample of 256 historical trials, capped at 512 by the preparation interface. Select the lowest SHA-256 values of `seed:NCT_ID`, independently of topics and qrels. Revalidate the entire rendered input, including row hashes and unique IDs, and preserve original trial provenance in the sample.

Use two pinned, Apache-2.0 model candidates:

| Alias | Repository | Revision | Dimensions | Token limit |
|---|---|---|---:|---:|
| minilm | sentence-transformers/all-MiniLM-L6-v2 | 1110a243fdf4706b3f48f1d95db1a4f5529b4d41 | 384 | 256 |
| pubmedbert | NeuML/pubmedbert-base-embeddings | b79526d6ef3645e0df4530322e266f24c829f5ef | 768 | 512 |

The [MiniLM model card](https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2) describes a lightweight general sentence encoder. The [PubMedBERT Embeddings model card](https://huggingface.co/NeuML/pubmedbert-base-embeddings) describes a biomedical sentence encoder trained on PubMed title/abstract pairs. Domain training is a reason to test the second candidate, not evidence that it improves this benchmark.

Download only allowlisted configuration/tokenizer files and safetensors weights. Do not download executable Python or pickle weights, and never enable remote code. Record local file hashes and the full model revision. Use Windows extended-length download paths because the hub creates long temporary filenames. Completed snapshots are verified and reused; incomplete model downloads may resume.

Inference loads local files only, runs on CPU in float32 with four threads by default, uses an explicit empty prompt, disables training behavior, and normalizes vectors to unit length. Record versions, platform, source hashes, batch size, model snapshot hash, token limits, and per-trial truncation. The initial document input is the existing `summary` representation without new labels or chunking. Synthetic queries use their original topic text.

Exact cosine search scores every document, in blocks, retaining the best results with NCT ID as the tie-breaker. It requires finite, normalized vectors with matching dimensions and rejects damaged artifacts or mismatched document/query models. No vector database, ANN index, dense age/sex filter, or eligibility decision is introduced here.

## Consequences

- Small samples expose operational defects before full-corpus encoding.
- A sample's search results cannot support TREC benchmark metrics or a claim of improvement over BM25. Artifacts explicitly prohibit benchmark scoring.
- Long input is truncated at the model limit, with every affected trial recorded. Different tokenizers and token limits must be considered before a fair full-corpus comparison.
- Successful preparation outputs are immutable. Failed sample/index preparation retains a failure manifest and issue details; incomplete outputs are rejected. Encoding restarts use a fresh output ID.
- Raw snapshots, models, sample documents, vectors, and detailed smoke reports remain local and Git-ignored. Public documentation contains only methods and reviewed aggregate findings.

## Validation

Tests compare blockwise search against direct matrix multiplication and cover ties, negative scores, invalid vectors, dimensions, IDs, checksums, unsafe paths, model mismatch, immutable outputs, and failure manifests. Real-model smoke checks repeat synthetic queries and re-encode saved documents to verify that document/query representations remain compatible. These checks measure operational correctness, not clinical relevance.
