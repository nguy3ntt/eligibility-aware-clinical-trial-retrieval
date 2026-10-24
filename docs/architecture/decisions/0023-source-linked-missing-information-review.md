# 0023: Order existing missing-information gaps without changing screening

Date: 2026-10-24. Status: accepted for bounded research use.

## Context

Screening retains unknowns and missing-information strings, but an unordered list does
not distinguish reusable fact gaps from unsupported interpretation. Asking for more
patient information cannot fix every parser/verifier limitation. The user requested
prioritisation for review, not new eligibility rules, medical urgency or test ordering.

## Decision

Add a separate, deterministic `missing-information-review-v1` artifact derived only
from source-reproduced ordinary assessments and, when supplied, reproduced grouped
packets. Its API display covers the selected pair; the reusable service also aggregates
up to ten trials of exactly the same synthetic case/version. Do not expand the patient
catalog, introduce text entry or recommend obtaining tests. CLI `--review` is explicit.

Only explicit existing missing/conflicting/uncertain patient evidence and same-unit gaps
in recognised predicates become fact-review items. Never infer a question from a type
tag, keyword or NLI advisory. Deduplicate by canonical fact name plus requested unit;
different units stay separate and no conversion is inferred. Every reference retains
assessment/trial/criterion/node IDs, original character spans, reasons and cited facts.

Order items by distinct trials without existing blockers, then distinct source criteria,
then total trials, then canonical fact/unit keys for stable ties. This is a reuse-based
worklist, not an information-gain estimate, a probability or clinical importance score.
Zero blockers does not mean eligibility; interpretation may still be unsupported.
Do not erase blockers or imply that one item will resolve an entire case/trial.

Keep all unsupported/preamble/scope problems in a separate interpretation queue. In
grouped mode a global scope guard takes precedence over local fact gaps. Unknown leaves
below a known AND/OR/NOT/conditional/waiver/exception expression are retained separately
as settled-branch unknowns, never promoted as active questions. Full grouped source
decisions remain unchanged. Count distinct original criteria, not duplicated tree wrappers.

New screening packets store the plan alongside, never inside, the original assessment.
Historical packets without this field remain readable and explicitly lack a recorded
plan; opening them must not compute new evidence. Implementation hashes and plan IDs
cover the ordering/provenance. Reproduction rejects modified counts, evidence, mixed
cases, duplicate trials, incompatible grouped inputs and changed source assessments.

## Validation and limits

Use authored synthetic contracts, repeated/cross-trial reuse, conflicts, units, known
blockers, unsupported wording and grouped settled branches. Audit the original 150
historical pairs for exact assessment/status invariance and exhaustive unknown
disposition; report how many fact-review opportunities actually exist. Fewer questions
is not accuracy. No independent reviewer, clinical benefit, expected information gain,
full clinical vocabulary or broad screening-coverage improvement is claimed. Preserve
all prior fixtures, studies, original models/indexes/defaults and ignored local data.
