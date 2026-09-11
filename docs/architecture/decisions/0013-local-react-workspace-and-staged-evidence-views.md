# ADR 0013: Local React workspace and staged evidence views

- Status: accepted for bounded local research
- Date: 2026-09-11

## Context

The versioned local API and evidence persistence are established. The requested first half of the interface must be useful independently while leaving dedicated screening, retrieval laboratory and experiment views for a coherent second increment. It must not broaden patient input or change unearned retrieval/screening promotion gates.

## Decision

Implement the first three planned objectives: search workspace, read-only extracted-fact review, and trial/criterion detail. Reuse `/v1` contracts. Curated synthetic IDs are the only patient input; fact review is observational and does not modify legacy age/sex filters. Search exposes result count but keeps exact dense and no reranking. Cards separate relevance from existing deterministic screening summaries. Raw evidence/provenance disclosures retain the response; the dedicated patient-to-criterion evidence panel remains subsequent work.

Use React/TypeScript/Vite with no router or global state framework yet. Shared request contracts, resource lifecycle and components support later screens without replacing the backend. This follows the supported [React build-tool approach](https://react.dev/learn/build-a-react-app-from-scratch) and [Vite React/TypeScript setup](https://vite.dev/guide/). Pin exact dependencies and commit the npm lockfile. No external font, telemetry or model provider is used at runtime.

Validate consumed API fields with Zod and retain unconsumed source/version fields. Check case/trial/search identities and reject contradictory result summaries. Retrieve all case pages, bound requests, cancel browser work and discard stale responses after selection changes. Never automatically retry a POST or show old results as a successful fallback. Cancelling a view does not claim cancellation of server work. Replayed operations are labelled saved historical results.

Vite and build preview bind to loopback port 5173 and proxy only `/v1` to the existing loopback API. No permissive CORS, client database credential, localStorage, account system or cloud hosting is added. A Windows wrapper manages only its verified project process. These are local tools, not production servers.

Use native controls, labelled statuses, visible focus, expandable evidence and a modal with Escape/close focus restoration. Source text is rendered as text, never injected HTML. Keep criterion wording, parent context and full sections available; the frontend performs no medical interpretation or re-verification.

## Consequences and continuity

The main lookup/search workflow is usable without API commands once services are started. The interface remains bounded and synchronous. Subsequent work extends typed operation contracts and adds the evidence panel, retrieval laboratory and experiment dashboard on these components. Model advice remains non-promoted and ranking metrics retain their diagnostic limits. No UI feature may imply broader clinical validation.

## Validation

Contract and interaction tests cover safe failures, invalid/contradictory packets, pagination, case-switch cancellation, duplicate submission prevention, empty results, replay labels and source views. Actual Chrome tests cover keyboard focus, narrow layouts and PostgreSQL/Qdrant-backed retrieval. Run TypeScript/build/format checks and backend regressions. Reports and milestone planning remain ignored; no automatic commits or pushes occur.
