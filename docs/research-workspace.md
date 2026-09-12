# Local browser research workspace

The browser workspace lets a reviewer choose a synthetic case, inspect extracted facts, retrieve trials, trace criterion outcomes to source evidence, compare retrieval configurations and reopen saved experiments. No real patient input, accounts, fact editing or cloud deployment is included. All inference uses the existing local API and pinned models.

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
7. Repeat the same search. Expect **Saved replay**, the same operation identity and result. A replay is historical stored evidence, not fresh inference. The full response remains available in a disclosure. **Inspect eligibility evidence** opens the dedicated screening workspace with that trial selected; click **Screen selected pair** to request the assessment explicitly.
8. Select a different case. Previous results must disappear immediately and the new facts must load before searching. Switching during a pending request must not show its eventual response under the new case. The server may still finish and save that operation.
9. Choose 5 or 10 results and search again. Existing results clear when the requested count changes. There is no eligibility-confidence slider or combined relevance/eligibility score.
10. Open **Trial catalog** independently of a case. Expect 446 records, 20 per page. **Next trials** changes the range to 21–40. Open a record to inspect the same source-detail view. Pagination does not silently reduce the catalog.
11. Try a narrow window or device emulation at 390 pixels wide. The workspace stacks into one column without horizontal page overflow. Keyboard users can reach the picker, search controls, result links and disclosures; the dialog retains focus until closed.

## Eligibility evidence walkthrough

1. Select **Invented demonstration · reranking-demo**, then open **Eligibility evidence**. The trial picker includes all 446 catalog records; its three `NCT9000900x` records are invented demonstrations, not benchmark evidence.
2. Select `NCT90009002` and click **Screen selected pair**. Expect **potential match** for this deliberately simple invented pair. Read the satisfied criteria and supporting facts. This remains bounded research screening requiring professional review, not confirmed medical eligibility.
3. Change to `NCT90009003`. The old result must clear immediately. Screen it and expect **likely exclusion**, with a violated criterion, a blocker and the cited synthetic evidence.
4. Change to `NCT90009001` and screen it. Expect **insufficient information** because the record deliberately lacks required evidence. Unknown outcomes must not appear satisfied.
5. For that same pair, select **Include optional learned NLI advisories** and screen again. A first run can take longer to load the local model. Expect separate **Learned NLI advisory · NOT PROMOTED** panels. The deterministic status remains insufficient information. Probabilities describe text relations only; model suggestions never resolve missing facts.
6. Expand **Complete case and trial context**, criterion provenance and advisory/model disclosures. Check exact source wording, source character offsets, ancestor context where present, fact assertion/temporality/certainty/experiencer, rule identity and missing items. Unsupported or complex historical criteria may all abstain; this is an existing coverage limitation, not an interface error.
7. Switch cases or screens while a request is pending. Old results must never appear under the new selection. Cancellation stops the browser's wait, not necessarily the server computation; a busy server may ask you to retry later.

## Retrieval laboratory walkthrough

1. Open **Retrieval laboratory** and choose `trec-ct-2022:29`. Leave the candidate at **Hybrid · RRF**, age/sex, legacy extractor and three displayed results. Click **Run comparison**. The baseline runs first, followed by the candidate; controls are disabled during the comparison.
2. Inspect displayed overlap and rank positions. A missing table position means absent from the shown top results, not absent from the entire candidate pool. Expand **Baseline results and evidence**. Baseline scores are cosine similarity and candidate scores are RRF, with no combined score or cross-scale score difference.
3. Change the candidate to **BM25 sparse** and run again. Candidate cards must identify **BM25 score · not eligibility**. Try **No metadata filter** to inspect that explicit variation; no benchmark improvement is inferred from one case.
4. Change to **Exact dense**, **Evidence-backed profile**, check **Opt into cross-encoder reranking**, and choose prefix **10**. Run again. Candidate cards show the learned cross-encoder score separately from the retained base score and original rank. Inspect model inputs and truncation in the ranking disclosure. Changing the extractor is an explicit experiment, not a change to normal search.
5. Read browser round-trip timings and the computed/replay labels. Replaying a stored operation is normally quicker, but this is not model latency or evidence of an algorithmic speed improvement. Full matched provenance remains available.
6. Return to **Search workspace**. Its defaults must still be exact dense, legacy age/sex, no reranking. Existing hybrid/reranking promotion gates remain unmet regardless of a favorable-looking example.

## Experiment dashboard walkthrough

1. Open **Experiment dashboard**. Saved searches, screenings, authored evaluations and imported reports appear in stable operation-ID order, not time order. Use **Next operations** when more than 20 are stored, or open a known operation ID directly. The number of stored operations depends on prior local usage.
2. Click **Run authored screening evaluation**. In the prepared workspace expect **passed: 34/34 exact pairs; 41 criteria**. These are authored development fixtures, not held-out or clinical validation. Repeat to see the same persisted operation with a **Saved replay** label.
3. Open a saved record and copy its **Stored operation identity** value. Reload the page, return to the dashboard and paste that 64-character hash into **Saved operation ID**. Click **Open saved operation**. The same historical result and provenance must reappear without model recomputation; arbitrary patient text is not accepted by this field.
4. Open the existing **reviewed experiment** for `m9-reranking-release`. Its stored operation ID is `f7ff5f0c1cc7f4727f302e94f4f47bc03da412d9c8485cf0a6526d1b2304e19b` in the prepared workspace. The nDCG@10 table should show approximately **0.5584 dense**, **0.5368 rerank-10**, **0.4956 rerank-20** and **0.3823 BM25**. This preserves the unfavorable reranking result; the UI must not imply reranker promotion. Read the visible limitations and pinned model revision. A fresh installation must explicitly import its reviewed report before this record is available; opening the dashboard does not import it.
5. Open saved screening and search operations too. They preserve their own case/configuration and evidence regardless of the currently selected case elsewhere in the application. Unknown report layouts retain the complete stored manifest without fabricated metrics. Tables may scroll horizontally within their container on narrow screens; the page itself should not overflow.

## Theme, project information and result details

Use the top-bar **Light mode / Dark mode** button to switch palettes. An explicit choice
survives a page refresh; no case or result evidence is stored in the browser. The initial
theme follows your operating system. **About the project** explains Themis Trial's academic
portfolio purpose, demonstrated skills and limitations, with GitHub profile/source links.
It remains readable even when the local services are unavailable.

In search results, underlined title phrases also occur in the trial's own source condition
or intervention fields. They are literal source-topic cues—not proof of a patient match.
Hover over a card to preview its recorded raw score, rank and topics, or use **Result details**
with touch/keyboard. Clicking keeps it open; Escape or × closes it. Reranker logits remain
separate and raw retrieval scores are not displayed as percentages. No new model call or
eligibility assessment is performed. Titles without literal source-topic overlap stay plain.

## Failure behavior

When the API is unavailable, affected views show a fixed message and **Try again** rather than old case results. To test this deliberately, stop the API using its wrapper and reload the browser; restart it and retry to recover. Do not stop unrelated services. A saved replay can remain available if only Qdrant is down, but readiness and fresh search cannot pass. Another active operation produces a retryable busy message. Invalid or contradictory packets are rejected before display.

No free-text patient entry exists. Never use real patient information to test the interface or API, even to test rejection.

## Automated verification

From `frontend/`, run `npm test`, `npm run build`, and `npm run format:check`. Set `RUN_UI_INTEGRATION=1` and run `npm run test:e2e` with services running for real Chrome integration. Default browser checks use tiny invented fixtures; live checks use the verified synthetic/public catalog, prepared local NLI/reranker models and the imported reranking report. They exercise screening, method comparisons, saved evaluation reopening and historical metric display, in addition to the search/source workflow. Traces, screenshots and generated assets stay ignored.

Full backend regression commands remain in the API guide. Frontend success does not resolve existing reranking, hybrid, semantic, broad screening or held-out validation gaps. The interface must remain local; internet deployment and authentication have not been assessed.
