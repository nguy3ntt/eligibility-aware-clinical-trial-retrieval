# Frontend

The frontend will use React and TypeScript after the API contract and core evaluation are stable.

## Planned pages

| Page | Features |
|---|---|
| Search workspace | synthetic patient input, filters, retrieval mode, ranked trial cards, score provenance |
| Trial detail | source metadata, interventions, locations, original and parsed criteria |
| Screening | extracted patient facts, criterion assessments, exclusions, missing information |
| Retrieval laboratory | BM25/dense/hybrid comparison, latency, ANN recall, per-query analysis |
| Experiment dashboard | model versions, metrics, ablations, significance, experiment history |

## UX rules

- Clearly display that only synthetic cases are permitted.
- Never present a similarity score as an eligibility probability.
- Keep retrieval relevance and eligibility assessment visually separate.
- Show exact evidence for every criterion assessment.
- Use `potential match`, `likely exclusion`, and `insufficient information` language.

No frontend package has been initialized yet. This avoids committing to an interface before the API and result schema are understood.
