# Themis Trial research workspace

React and TypeScript provide curated synthetic-case selection, read-only fact review, trial search/source inspection, criterion-to-fact screening evidence, retrieval comparisons and persisted experiment review. No arbitrary patient text or fact editing is accepted.

## Run locally

Use Node 24.16+ and npm. From this directory:

```powershell
npm ci
npm run dev
```

Open <http://127.0.0.1:5173>. The existing API must run on loopback port 8000 with its prepared PostgreSQL catalog, Qdrant indexes and local models. The [manual guide](../docs/research-workspace.md) includes startup commands and expected results. From the repository root, `./scripts/frontend-local.ps1 -Action Start|Stop|Status` manages a hidden frontend process without installing dependencies or modifying evidence.

Browser requests use relative `/v1` paths through a fixed local Vite proxy. API protections are unchanged; no permissive CORS, client credentials, telemetry or browser evidence persistence is introduced. Only the explicit light/dark preference is stored locally. Development and preview servers bind to loopback with strict port 5173. Neither is qualified for public deployment.

## Presentation and About

Themis Trial preserves the original light palette and adds a forest-ink dark theme.
The top-bar toggle follows the system preference initially and remembers only an explicit
`light`/`dark` selection. With storage disabled it still works for the current page.
The static About view explains the academic portfolio purpose, demonstrated skills and
research limitations, with links to the repository owner's GitHub profile and source.

Result titles underline literal words shared with their own condition/intervention source
fields. Generic terms are excluded; source titles and evidence remain unchanged. These
are source-topic cues, not patient-fact matches or model-attribution explanations. Hover
previews and the accessible **Result details** button expose the same raw score/rank,
source topics and optional separate reranker logit. Click to keep the panel open; close it
with the button, × or Escape. Mobile panels are inline. Scores are never presented as
calibrated match percentages. See [ADR 0016](../docs/architecture/decisions/0016-themis-presentation-and-source-highlights.md).

## Structure and contracts

- `src/api/contracts.ts`: runtime validation and inferred types; unconsumed version/provenance fields are preserved.
- `src/api/client.ts`: complete bounded pagination, fixed default search, identity checks, safe errors and cancellation.
- `src/api/workbenchContracts.ts`: validated full screening, non-promoted NLI and saved-operation contracts.
- `src/api/workbench.ts`: explicit laboratory requests, complete trial choices, saved operations and comparison provenance checks.
- `src/hooks/useResource.ts`: loading, retry and stale-response suppression.
- `src/hooks/useOperation.ts`: explicit mutations, duplicate-submit protection and cancellation without automatic POST retries.
- `src/components/`: reusable profile, result, trial-source and evidence disclosures.
- `src/App.tsx`: case selection and search lifecycle; changing cases discards prior results and pending responses.
- `src/test/`: deliberately tiny invented fixtures only.
- `e2e/`: real Chrome keyboard/mobile tests and opt-in real API integration.

Ordinary search stays exact dense, legacy age/sex, no reranking; result count is 3, 5 or 10. Fact review does not change filters. Trial detail is source parsing; only an explicit screening request assesses a selected synthetic pair. Full criterion outcomes retain ancestor/source context, cited fact evidence, blockers and unknowns. Optional learned NLI is separately labelled NOT PROMOTED.

The laboratory runs baseline and candidate requests sequentially, validates both configurations and checks catalog, code, runtime and index contracts before displaying comparisons. Object key order from PostgreSQL replay is insignificant; array order and values remain significant. Cosine, BM25, RRF and cross-encoder outputs stay separate; displayed overlap is not recall and browser round-trip time is not model latency. Configurations never alter ordinary search defaults.

The dashboard lists immutable operations in ID order, opens stored evidence without recomputation and runs only the existing authored screening fixture evaluation. Historical metrics preserve negative findings, model identities and validation limitations. No new benchmark, model promotion or deployment is performed. See [ADR 0013](../docs/architecture/decisions/0013-local-react-workspace-and-staged-evidence-views.md) and [ADR 0014](../docs/architecture/decisions/0014-evidence-comparisons-and-saved-experiments.md).

## Verification

For an opt-in actual-service five-scene video and screenshots, set `RUN_RELEASE_DEMO=1`
and run `npx playwright test e2e/release-demo.spec.ts` after installing Playwright's Chrome
and ffmpeg components. The recording uses only verified synthetic/public evidence and
remains under ignored `test-results/`; subsequent browser runs replace that directory.
See [release reproduction](../docs/research-release.md).

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
