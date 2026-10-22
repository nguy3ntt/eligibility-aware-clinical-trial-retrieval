# 0021 — Separate field and passage retrieval artifact

Date: 2026-10-22. Status: accepted as an experimental, opt-in extension.

The user requested richer first-stage representations with field/passage evidence.
Keep the active 443-trial Qdrant collection, exact dense default, pinned MiniLM and
historical full-corpus study unchanged. Building a full-corpus criterion-vector index
or tuning on the consumed 2021 test cases is not part of this request.

Create a separate immutable `field-passages-v1` artifact format. The completed final
generation is `field-passages-v2`; preliminary generation v1 remains local and unused.
Explicit preparation reads the verified dense index and XML field-evidence artifact.
It never downloads or silently builds during an API request. Sources cap at 512 trials
and 50,000 total comparison segments. Application configuration selects the optional
artifact using `api_passage_id`; a missing artifact returns an actionable 503.

Reuse the exact existing title/condition vectors. Additional branches are brief summary,
detailed description and intervention names, each retaining individual original text
items. Split using the pinned fast tokenizer's original-character offsets into 192-token
windows with 32-token overlap. Preserve original text, XML locator, item, character and
token ranges, XML hash and full/retained token metadata. No eligibility text is indexed.
Passages must fit the model limit without truncation; whole-summary and whole-field
controls explicitly record truncation. Query text/encoder/truncation and legacy filters
remain identical across the dense comparisons.

Within each field, select the maximum cosine per trial. Each field contributes at most
once to a trial's equal-branch RRF score, constant 60 and branch depth 100. Preserve raw
cosines, branch ranks, contributing segments and RRF contributions separately. Stable
NCT-ID ties and trial-level deduplication are required. Max pooling still has possible
long-document selection bias; RRF also favors trials with more available fields. These
are limitations to measure, not assumed advantages or calibrated match probabilities.

Load verifies file inventory/hashes, source spans, field completeness, window continuity,
statistics, exact saved baseline vectors and current source implementation. Query runtime
and model metadata must agree. The app verifies the source against its immutable database
catalog. The catalog's hybrid contract extends the same dense source contract; compare
that explicit relationship rather than asserting the two contract objects are identical.
Include the passage manifest hash in saved operation identity. Keep the original catalog
contract in API output so controlled baseline/candidate comparisons remain possible.

The fixed development study saves BM25 title/summary baselines before dense comparisons,
then compares baseline, summary, whole-field fusion and passage fusion on the same
judgment-selected pool. It is not a fresh holdout or full-corpus study. Observed passage
fusion worsens top-ten quality; it is not promoted or retuned to improve the reported
result. Browser laboratory selection is explicit, and source disclosures show what
actually contributed. No new dependency, infrastructure or deployment is introduced.
