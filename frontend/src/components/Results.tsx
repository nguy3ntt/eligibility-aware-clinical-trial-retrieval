import type { Search } from "../api/contracts";
import { useId } from "react";
import { JsonEvidence, StatusBadge } from "./Common";

export function Results({
  search,
  openTrial,
  screenPair,
}: {
  search: Search;
  openTrial: (id: string) => void;
  screenPair?: (id: string) => void;
}) {
  const heading = useId();
  return (
    <section aria-labelledby={heading}>
      <div className="section-heading">
        <h2 id={heading}>
          Retrieved trials{" "}
          <span className="count">{search.result.results.length}</span>
        </h2>
        <span className="badge neutral">
          {search.replayed ? "Saved replay" : "Newly computed"}
        </span>
      </div>
      <p className="muted small">
        Case {search.request.case_id} · {search.result.candidate_count}{" "}
        candidates · {search.result.method} relevance
        {search.result.reranker ? " · reranked prefix" : ""}
      </p>
      <p className="small">
        {search.replayed
          ? "This is a stored operation, not a fresh search or assessment."
          : "This completed operation is saved with its source and model versions."}
      </p>
      {search.result.query_truncated && (
        <p className="notice">
          The query exceeded the encoder limit and was shortened. Full source
          evidence is retained.
        </p>
      )}
      {search.result.results.length === 0 && (
        <div className="empty">
          <h3>No candidates returned</h3>
          <p>
            This bounded index and filter found no result. It does not establish
            that no relevant trial exists.
          </p>
        </div>
      )}
      <ol className="results-list">
        {search.result.results.map((result) => (
          <li className="result-card" key={result.trial_id}>
            <div className="result-top">
              <span className="rank">
                {String(result.relevance.ranking.rank).padStart(2, "0")}
              </span>
              <span className="eyebrow">{result.trial_id}</span>
            </div>
            <h3>
              <button
                className="title-button"
                onClick={() => openTrial(result.trial_id)}
              >
                {result.relevance.fields.brief_title?.normalized ||
                  result.trial_id}
              </button>
            </h3>
            <p className="summary-text">
              {result.relevance.fields.brief_summary?.normalized ||
                "No summary was supplied in the source."}
            </p>
            <div className="result-measures">
              <div>
                <span className="metric-label">Retrieval relevance</span>
                <strong className="score">
                  {result.relevance.ranking.score.toFixed(4)}
                </strong>
                <span className="small muted">
                  {search.result.method === "dense"
                    ? "Cosine similarity"
                    : search.result.method === "sparse"
                      ? "BM25 score"
                      : "RRF score"}{" "}
                  · not eligibility
                </span>
                {result.relevance.ranking.reranker && (
                  <>
                    <span className="small">
                      Learned cross-encoder:{" "}
                      {result.relevance.ranking.reranker.score.toFixed(4)}
                    </span>
                    <span className="small muted">
                      Original rank {result.relevance.ranking.original_rank};
                      base retrieval score retained above.
                    </span>
                  </>
                )}
              </div>
              <div>
                <span className="metric-label">Deterministic screening</span>
                <StatusBadge status={result.screening.status} />
                <span className="small muted">
                  Requires professional review
                </span>
              </div>
            </div>
            <button
              className="text-button"
              onClick={() => openTrial(result.trial_id)}
              aria-label={`View trial ${result.trial_id}`}
            >
              Read trial & criteria <span aria-hidden="true">→</span>
            </button>
            {screenPair && (
              <button
                className="text-button screen-pair"
                onClick={() => screenPair(result.trial_id)}
                aria-label={`Screen pair ${result.trial_id}`}
              >
                Inspect eligibility evidence →
              </button>
            )}
            <JsonEvidence
              value={result.relevance.ranking}
              label="Ranking branches and model inputs"
            />
          </li>
        ))}
      </ol>
      <details className="evidence">
        <summary>Operation identity</summary>
        <dl>
          <dt>Operation</dt>
          <dd className="mono">{search.operation_id}</dd>
          <dt>Catalog</dt>
          <dd>{search.provenance.catalog_id}</dd>
          <dt>Code fingerprint</dt>
          <dd className="mono">{search.provenance.implementation_sha256}</dd>
        </dl>
      </details>
      <JsonEvidence value={search} label="Full stored response and evidence" />
    </section>
  );
}
