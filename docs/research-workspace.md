# Local browser research workspace

The first browser workflow lets a reviewer choose a synthetic case, inspect its extracted facts, retrieve trials and read original trial/criterion evidence. The remaining views are a dedicated eligibility evidence panel, retrieval laboratory and experiment dashboard. No real patient input, accounts, fact editing or cloud deployment is included.

## Start this prepared workspace

Run from the nested Git repository in PowerShell:

```powershell
cd E:\eligibility-aware-clinical-trial-retrieval\eligibility-aware-clinical-trial-retrieval
.\scripts\postgres-local.ps1 -Action Start
.\scripts\qdrant-local.ps1 -Action Start
.\scripts\api-local.ps1 -Action Start
.\scripts\frontend-local.ps1 -Action Start
```

Open [the research workspace](http://127.0.0.1:5173). Normal review and search now happen in the browser, without API commands. The wrappers run hidden local processes and preserve data when stopped. Use `-Action Stop` to stop a project service; the frontend wrapper does not stop the databases or API. No service is configured to start at Windows login.

For a fresh frontend installation, use Node 24.16+ and run `npm ci` inside `frontend/`. API/data/model prerequisites remain in the [API operating guide](local-research-api.md). Do not copy database credentials into frontend files. No model or source download happens when starting the frontend.

## Manual walkthrough and expected behavior

1. Confirm **Services ready** in the top bar and read the synthetic-only safety notice. Clicking the service indicator repeats readiness inspection; it does not start services or download models. Readiness checks databases/catalog/index contracts; model loading remains lazy.
2. Open **Choose a synthetic case**. All 51 cases should be present, including `reranking-demo` and all 50 TREC cases. Select `trec-ct-2022:29`.
3. Review the read-only narrative and **Extracted facts**. Age, sex and supported condition mentions retain assertion, temporality, certainty and experiencer. The uncertain cauda-equina mention must stay uncertain. Expand **Source evidence** to inspect exact wording, character spans, context and rule identity. Expand **Extraction review notes** and **Full profile and provenance** for the retained audit. Unextracted information is explicitly unknown; no fact editing is supported.
4. Leave **Results to show** at 3 and click **Search trials**. The first fresh search can take longer while the local model loads. The UI displays exact dense, legacy age/sex and no reranking; reviewing richer facts does not alter these defaults.
5. Expect `NCT01726751`, `NCT03325374`, `NCT02749071` in that order. Their cosine scores are approximately 0.4734, 0.4561 and 0.3612. These are relevance scores, not eligibility probabilities. Each screening summary remains **insufficient information**, with professional review required.
6. Click a trial title or **Read trial & criteria**. Read the summary and original field locators, parsed inclusion/exclusion clauses, parent context and review reasons. Expand **Complete original eligibility wording** and **Complete trial and parser provenance**. Parsing a clause does not mean the synthetic patient satisfies it. Close with **Close detail** or Escape; focus returns to the opening control.
7. Repeat the same search. Expect **Saved replay**, the same operation identity and result. A replay is historical stored evidence, not fresh inference. The full response, including criterion assessments, remains available in a disclosure; a dedicated screening evidence interface comes later.
8. Select a different case. Previous results must disappear immediately and the new facts must load before searching. Switching during a pending request must not show its eventual response under the new case. The server may still finish and save that operation.
9. Choose 5 or 10 results and search again. Existing results clear when the requested count changes. There is no eligibility-confidence slider or combined relevance/eligibility score.
10. Open **Trial catalog** independently of a case. Expect 446 records, 20 per page. **Next trials** changes the range to 21–40. Open a record to inspect the same source-detail view. Pagination does not silently reduce the catalog.
11. Try a narrow window or device emulation at 390 pixels wide. The workspace stacks into one column without horizontal page overflow. Keyboard users can reach the picker, search controls, result links and disclosures; the dialog retains focus until closed.

## Failure behavior

When the API is unavailable, affected views show a fixed message and **Try again** rather than old case results. To test this deliberately, stop the API using its wrapper and reload the browser; restart it and retry to recover. Do not stop unrelated services. A saved replay can remain available if only Qdrant is down, but readiness and fresh search cannot pass. Another active operation produces a retryable busy message. Invalid or contradictory packets are rejected before display.

No free-text patient entry exists. Never use real patient information to test the interface or API, even to test rejection.

## Automated verification

From `frontend/`, run `npm test`, `npm run build`, and `npm run format:check`. Set `RUN_UI_INTEGRATION=1` and run `npm run test:e2e` with services running for real Chrome integration. Default browser checks use tiny invented fixtures; live checks use the verified synthetic/public catalog. Traces, screenshots and generated assets stay ignored.

Full backend regression commands remain in the API guide. Frontend success does not resolve existing reranking, hybrid, semantic, broad screening or held-out validation gaps. The interface must remain local; internet deployment and authentication have not been assessed.
