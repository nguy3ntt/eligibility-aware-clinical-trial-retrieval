# 0020 — Source-preserving grouped screening

Date: 2026-10-22. Status: accepted as an experimental, opt-in extension.

The user requested grouped eligibility logic while preserving provenance and uncertainty.
The original v1 parser, criterion IDs, v2 verifier, ordinary screening contract and learned
advisories remain unchanged. Flattening alternatives into independent criterion blockers
would misinterpret OR and exceptions; changing the existing trial-summary validator would
also make historical evidence ambiguous.

Add `grouped-screening-v1` as a separate interpretation of the freshly validated source.
Its tree contains exact source spans, original criterion IDs, patient fact IDs, explicit
operators and true/false/unknown predicates. Use strong Kleene logic. Inclusion sections
combine independent requirements with AND; exclusion sections combine exclusion predicates
with OR. Only section conclusions create trial blockers, never an isolated failed OR child.
Require applicable supported inclusion evidence before returning a potential match.

The bounded grammar supports homogeneous inline AND/OR, explicit parentheses, NOT,
canonical list headings, explicit inclusion conditionals, inclusion requirement waivers
and exclusion exceptions. Mixed unparenthesized operators and bare ambiguous `unless`
remain unknown. An unrecognised group, preamble or unresolved shared scope prevents all
section conclusions. Balanced descriptive parentheses in an unrelated unsupported clause
do not erase an independently supported age blocker. Unsupported atoms remain unknown;
no diagnosis inference, unit conversion, timing interpretation or learned promotion occurs.

Nodes/depth are bounded; excessive input fails rather than dropping criteria. The original
parse is retained and every original criterion must occur in the tree. Stored grouped
packets can be reproduced from source with `validate_grouped`. API `grouped: true` and CLI
`--grouped` opt in; browser screening and saved operations display it separately from the
ordinary assessment. Default requests never activate the extension.

Thirty authored synthetic contracts and exhaustive possible-world truth-table checks
verify engineering behavior. The historical audit is unlabelled development coverage,
not independently reviewed criterion accuracy. No new clinical validation is claimed.
See [methods and manual tests](../../grouped-and-passage-methods.md).
