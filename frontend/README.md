# Research workspace

React and TypeScript provide curated synthetic-case selection, read-only extracted-fact review, default trial search, and trial/criterion source inspection. No arbitrary patient text or fact editing is accepted. The dedicated screening evidence panel, retrieval laboratory and experiment dashboard remain subsequent work.

## Run locally

Use Node 24.16+ and npm. From this directory:

```powershell
npm ci
npm run dev
```

Open <http://127.0.0.1:5173>. The existing API must run on loopback port 8000 with its prepared PostgreSQL catalog, Qdrant indexes and local models. The [manual guide](../docs/research-workspace.md) includes startup commands and expected results. From the repository root, `./scripts/frontend-local.ps1 -Action Start|Stop|Status` manages a hidden frontend process without installing dependencies or modifying evidence.

Browser requests use relative `/v1` paths through a fixed local Vite proxy. API protections are unchanged; no permissive CORS, client credentials, telemetry or browser persistence is introduced. Development and preview servers bind to loopback with strict port 5173. Neither is qualified for public deployment.

## Structure and contracts

- `src/api/contracts.ts`: runtime validation and inferred types; unconsumed version/provenance fields are preserved.
- `src/api/client.ts`: complete bounded pagination, fixed default search, identity checks, safe errors and cancellation.
- `src/hooks/useResource.ts`: loading, retry and stale-response suppression.
- `src/components/`: reusable profile, result, trial-source and evidence disclosures.
- `src/App.tsx`: case selection and search lifecycle; changing cases discards prior results and pending responses.
- `src/test/`: deliberately tiny invented fixtures only.
- `e2e/`: real Chrome keyboard/mobile tests and opt-in real API integration.

Search stays exact dense, legacy age/sex, no reranking; result count is 3, 5 or 10. Fact review does not change filters. Every score is labelled as retrieval relevance rather than eligibility. Screening summaries retain deterministic API labels. Full response records remain inspectable; the dedicated criterion-to-patient evidence panel is not implemented yet. Trial detail is source parsing, not a new patient assessment.

The second half can reuse the client, resource lifecycle, disclosures and layout. Extend validated method/operation contracts explicitly for laboratory and experiment views; do not bypass validation or silently change defaults. See [ADR 0013](../docs/architecture/decisions/0013-local-react-workspace-and-staged-evidence-views.md).

## Verification

```powershell
npm run build
npm test
npm run format:check
npm run test:e2e
```

Browser tests use installed Chrome. The real-service test is skipped unless `RUN_UI_INTEGRATION=1`; start the existing services first:

```powershell
$env:RUN_UI_INTEGRATION='1'
npm run test:e2e
```

The browser suite starts Vite when needed or reuses port 5173. Keep that port reserved for this project. `npm run preview` locally checks a production build with the same proxy. Builds, traces, screenshots and reports remain ignored; publish source, tiny fixtures and `package-lock.json`. This does not establish clinical accuracy, retrieval improvement or production hardening.
