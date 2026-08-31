# Safety and limitations

## Intended use

This is an educational research system for studying information retrieval, vector databases, and explainable eligibility screening using public trial information and synthetic patient cases.

## Prohibited uses

- medical diagnosis;
- treatment recommendation;
- confirmed clinical-trial eligibility decisions;
- autonomous patient recruitment;
- processing real identifiable patient information;
- replacing trial investigators or qualified clinicians.

## Required output language

Use:

- potential match;
- likely exclusion;
- insufficient information;
- requires professional review.

Do not use:

- confirmed eligible;
- safe for this patient;
- recommended treatment;
- medically approved by this system.

## Key limitations

- Trial records may be incomplete, outdated, inconsistent, or ambiguously written.
- Relevance judgments cover only assessed query–trial pairs.
- Synthetic patient cases do not reproduce every property of real clinical records.
- Embedding similarity does not demonstrate clinical compatibility.
- Eligibility may depend on tests, investigator judgment, or facts absent from the case.
- Negation, temporality, units, and multi-clause logic are difficult to parse reliably.
- Trial availability and recruitment status can change.

## Privacy boundary

The application must display that only synthetic case text is permitted. Logs must not include unbounded request bodies. Test fixtures must be visibly synthetic and must not be copied from private health records.

## Evidence requirement

Every eligibility assessment must retain:

- exact trial criterion text;
- source section and trial ID;
- supporting synthetic patient fact;
- method and model/parser version;
- confidence or deterministic rule status.

An unsupported explanation is a system defect.
