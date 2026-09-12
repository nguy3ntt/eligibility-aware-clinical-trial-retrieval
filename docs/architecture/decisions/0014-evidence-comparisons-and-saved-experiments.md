# ADR 0014: Evidence, comparisons and saved experiments

- Status: accepted for bounded local research
- Date: 2026-09-11

## Context

The existing browser search, fact review and trial-source views leave three research workflows accessible only through the API. Complete the interface on the established contracts without changing retrieval defaults, adding inference logic, or treating the small diagnostic pool as clinical validation.

## Decision

Add a dedicated screening workspace using curated synthetic case and trial IDs. Every criterion remains visible in source order, with inclusion/exclusion and ancestor context, exact wording, deterministic outcome, rule identity, cited facts, blockers and missing information. Complete narrative, source sections and provenance remain inspectable. Validate criterion/fact identities, source spans, summary consistency and learned-advisory alignment before display. Unicode evidence offsets follow the backend's code-point convention.

NLI is an explicit opt-in and remains a separate non-promoted advisory. Its text-relation probabilities never become eligibility probabilities or overwrite deterministic outcomes. Opening trial source detail does not trigger screening.

The retrieval laboratory compares an explicit candidate against exact dense plus legacy age/sex at the same displayed depth. Candidate controls expose existing dense/sparse/hybrid, metadata-filter, extractor and bounded cross-encoder options. Run requests sequentially to respect the server's operation gate. Require matching case, catalog, implementation, runtime versions and retrieval/index contract. Compare JSON object contents independently of key order because PostgreSQL JSONB can reorder keys on replay; retain array order and all value differences. If either request fails or provenance differs, withhold the comparison.

Display rank movement and overlap only among shown results. Preserve original ranks and base retrieval scores under reranking. Cosine, BM25, reciprocal-rank fusion and raw cross-encoder scores use separate labels and are never added or subtracted across scales. Browser request timing explicitly includes transport, persistence and replay; it is not model-only latency or a quality benchmark. No control changes ordinary search defaults.

The experiment dashboard reads immutable saved search/screening/evaluation operations and imported historical reports, with bounded pagination in stable ID order. Opening a saved operation never reruns it. Only the existing authored screening fixture evaluation can be requested. Historical metric tables show recorded values, including regressions, alongside limitations and model/promotion provenance. Unknown report layouts retain their full manifest without invented metrics.

Reuse the existing request lifecycle, safe fixed errors, evidence components and responsive layout. Cancel and discard stale browser work when selections change; never automatically retry POSTs. Server work may still finish after cancellation. Add no dependencies, credentials, patient text entry, accounts, browser persistence, backend changes or public hosting.

## Validation and consequences

Contract and interaction tests cover contradictory evidence, score meanings, provenance changes, JSONB key order, explicit opt-ins, sequential requests, failed comparisons, cancellation, history lookup and historical limitations. Real Chrome tests exercise all three screening statuses, pinned NLI and reranker outputs, hybrid comparisons, persisted evaluation reopening, negative historical metrics and narrow layouts. Existing backend/model/database regressions remain required.

The full local review workflow is now browser-accessible after service startup. This is an interface completion, not a retrieval improvement or clinical validation claim. Full-corpus/held-out evaluation, broad screening coverage, production hardening and public deployment remain outside this change. Tracking, screenshots, test reports and generated assets remain private and ignored.
