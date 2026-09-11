import type { Search } from "../api/contracts";
import { JsonEvidence, StatusBadge } from "./Common";

export function Results({
  search,
  openTrial,
}: {
  search: Search;
  openTrial: (id: string) => void;
}) {
  return (
    <section aria-labelledby="results-title">
      <div className="section-heading">
        <h2 id="results-title">
          Retrieved trials{" "}
          <span className="count">{search.result.results.length}</span>
        </h2>
        <span className="badge neutral">
          {search.replayed ? "Saved replay" : "Newly computed"}
        </span>
      </div>
      <p className="muted small">
        Case {search.request.case_id} · {search.result.candidate_count}{" "}
        candidates · exact dense relevance
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
                  Cosine similarity · not eligibility
                </span>
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
