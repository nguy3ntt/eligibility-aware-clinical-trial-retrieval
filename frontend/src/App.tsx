import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api/client";
import type { Search } from "./api/contracts";
import { CaseReview } from "./components/CaseReview";
import { ErrorPanel, Loading } from "./components/Common";
import { Results } from "./components/Results";
import { TrialCatalog } from "./components/TrialCatalog";
import { TrialDialog } from "./components/TrialDialog";
import { useResource } from "./hooks/useResource";

function CaseWorkspace({
  id,
  openTrial,
}: {
  id: string;
  openTrial: (id: string) => void;
}) {
  const load = useCallback(
    (signal: AbortSignal) => api.profile(id, signal),
    [id],
  );
  const { state, retry } = useResource(load);
  const [topK, setTopK] = useState(3);
  const [search, setSearch] = useState<Search | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const operation = useRef<AbortController | null>(null);
  useEffect(() => () => operation.current?.abort(), []);
  async function runSearch() {
    if (operation.current || state.status !== "ready") return;
    const controller = new AbortController();
    operation.current = controller;
    setBusy(true);
    setError(null);
    setSearch(null);
    try {
      const result = await api.search(id, topK, controller.signal);
      if (!controller.signal.aborted) setSearch(result);
    } catch (error) {
      if (!controller.signal.aborted)
        setError(error instanceof Error ? error.message : "Search failed.");
    } finally {
      if (!controller.signal.aborted) {
        setBusy(false);
        operation.current = null;
      }
    }
  }
  return (
    <div className="workspace-grid">
      <aside className="panel case-panel">
        {state.status === "loading" ? (
          <Loading label="Loading synthetic case…" />
        ) : state.status === "error" ? (
          <ErrorPanel message={state.message} retry={retry} />
        ) : (
          <CaseReview profile={state.data} />
        )}
      </aside>
      <div className="search-column">
        <section
          className="panel search-controls"
          aria-labelledby="search-title"
        >
          <div className="section-heading">
            <h2 id="search-title">Find relevant trials</h2>
            <span className="badge neutral">Established defaults</span>
          </div>
          <div className="tags defaults">
            <span>Exact dense</span>
            <span>Legacy age / sex</span>
            <span>No reranking</span>
          </div>
          <p className="muted">
            Search the bounded historical index. Trial relevance and
            deterministic screening answer different questions.
          </p>
          <form
            onSubmit={(event) => {
              event.preventDefault();
              void runSearch();
            }}
          >
            <label>
              Results to show
              <select
                value={topK}
                disabled={busy}
                onChange={(event) => {
                  setTopK(Number(event.target.value));
                  setSearch(null);
                  setError(null);
                }}
              >
                {[3, 5, 10].map((n) => (
                  <option key={n} value={n}>
                    {n} trials
                  </option>
                ))}
              </select>
            </label>
            <button
              className="primary"
              disabled={busy || state.status !== "ready"}
              type="submit"
            >
              {busy ? "Searching…" : "Search trials"}
              <span aria-hidden="true">↗</span>
            </button>
          </form>
        </section>
        {busy && (
          <div className="panel">
            <Loading label="Retrieving and checking source evidence…" />
            <p className="small muted">
              The first search may take longer while the local model loads.
              Switching cases discards this view, but the server may still
              finish the operation.
            </p>
          </div>
        )}
        {error && <ErrorPanel message={error} retry={() => void runSearch()} />}
        {search && <Results search={search} openTrial={openTrial} />}
        {!busy && !error && !search && (
          <div className="empty">
            <span className="empty-symbol" aria-hidden="true">
              ⌕
            </span>
            <h2>Start with the evidence.</h2>
            <p>
              Review the synthetic case, then search for relevant trials.
              <br />
              Every result keeps its source and screening context.
            </p>
            <p className="small muted">
              A match is a research lead. It is never confirmed eligibility.
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
export function App() {
  const { state: cases, retry: retryCases } = useResource(api.cases);
  const { state: ready, retry: retryReady } = useResource(api.ready);
  const [caseId, setCaseId] = useState("");
  const [page, setPage] = useState<"search" | "trials">("search");
  const [trial, setTrial] = useState<string | null>(null);
  return (
    <div className="app-shell">
      <a className="skip-link" href="#main">
        Skip to workspace
      </a>
      <aside className="sidebar">
        <a href="#main" className="brand">
          <span className="brand-mark" aria-hidden="true">
            ✳
          </span>
          <span>
            Trial Atlas<small>RESEARCH WORKSPACE</small>
          </span>
        </a>
        <p className="nav-label">EXPLORE</p>
        <nav aria-label="Workspace">
          <button
            aria-current={page === "search" ? "page" : undefined}
            onClick={() => setPage("search")}
          >
            <span aria-hidden="true">⌕</span> Search workspace
          </button>
          <button
            aria-current={page === "trials" ? "page" : undefined}
            onClick={() => setPage("trials")}
          >
            <span aria-hidden="true">▤</span> Trial catalog
          </button>
        </nav>
        <div className="sidebar-note">
          <span className="status-dot" />
          LOCAL RESEARCH
          <p>
            Public trial evidence.
            <br />
            Synthetic cases only.
          </p>
          <small>No clinical decisions.</small>
        </div>
      </aside>
      <div className="main-shell">
        <header className="topbar">
          <span>
            Clinical-trial retrieval{" "}
            <span className="muted">
              / {page === "search" ? "Workspace" : "Catalog"}
            </span>
          </span>
          <button
            className="service-state"
            onClick={retryReady}
            aria-label="Refresh service readiness"
          >
            <span
              className={`status-dot ${ready.status === "ready" ? "" : "warning"}`}
            />
            {ready.status === "ready"
              ? "Services ready"
              : ready.status === "loading"
                ? "Checking services…"
                : "Check local services"}
          </button>
        </header>
        <main id="main">
          <div className="page-heading">
            <div>
              <p className="eyebrow">EVIDENCE BEFORE INTERPRETATION</p>
              <h1>
                {page === "search"
                  ? "Explore potential matches."
                  : "Read the source."}
              </h1>
              <p className="muted">
                An explainable research workspace for synthetic patient cases.
              </p>
            </div>
            <span className="research-tag">RESEARCH ONLY</span>
          </div>
          <div className="safety-banner">
            <strong>Synthetic cases only.</strong> Not medical advice or
            confirmed eligibility. Missing information remains unknown. Requires
            professional review.
          </div>
          {ready.status === "error" && (
            <div className="notice" role="status">
              Readiness could not be confirmed. Saved records may still be
              available. {ready.message}
            </div>
          )}
          {page === "trials" ? (
            <TrialCatalog openTrial={setTrial} />
          ) : (
            <>
              <section
                className="case-selector panel"
                aria-label="Synthetic catalog selection"
              >
                {cases.status === "loading" ? (
                  <Loading label="Loading the synthetic catalog…" />
                ) : cases.status === "error" ? (
                  <ErrorPanel message={cases.message} retry={retryCases} />
                ) : (
                  <>
                    <label htmlFor="case-select">
                      Choose a synthetic case
                      <select
                        id="case-select"
                        value={caseId}
                        onChange={(event) => setCaseId(event.target.value)}
                      >
                        <option value="">Select a case to begin</option>
                        {cases.data.map((c) => (
                          <option key={c.case_id} value={c.case_id}>
                            {c.case_id === "reranking-demo"
                              ? "Invented demonstration · reranking-demo"
                              : c.case_id}
                          </option>
                        ))}
                      </select>
                    </label>
                    <p className="small muted">
                      {cases.data.length} verified synthetic cases
                      <br />
                      No patient text uploads or edits
                    </p>
                  </>
                )}
              </section>
              {caseId ? (
                <CaseWorkspace key={caseId} id={caseId} openTrial={setTrial} />
              ) : (
                <div className="empty welcome">
                  <span className="empty-symbol" aria-hidden="true">
                    ⌕
                  </span>
                  <h2>A case. Its facts. The original evidence.</h2>
                  <p>
                    Choose a synthetic case above to review extracted facts
                    <br />
                    and explore the bounded trial index.
                  </p>
                </div>
              )}
            </>
          )}
          <footer>
            Bounded research prototype · Retrieval relevance ≠ medical
            eligibility · No learned screening promotion
          </footer>
        </main>
      </div>
      {trial && (
        <TrialDialog key={trial} id={trial} close={() => setTrial(null)} />
      )}
    </div>
  );
}
