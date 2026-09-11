import { useCallback, useState } from "react";
import { api } from "../api/client";
import { useResource } from "../hooks/useResource";
import { ErrorPanel, Loading, words } from "./Common";

export function TrialCatalog({
  openTrial,
}: {
  openTrial: (id: string) => void;
}) {
  const [offset, setOffset] = useState(0);
  const load = useCallback(
    (signal: AbortSignal) => api.trials(offset, signal),
    [offset],
  );
  const { state, retry } = useResource(load);
  return (
    <section className="panel catalog">
      <div className="section-heading">
        <h2>Trial catalog</h2>
        <span className="badge neutral">Source inspection</span>
      </div>
      <p className="muted">
        Browse public historical records and invented demonstrations
        independently of a search. No patient assessment is performed here.
      </p>
      {state.status === "loading" ? (
        <Loading label="Loading trial catalog…" />
      ) : state.status === "error" ? (
        <ErrorPanel message={state.message} retry={retry} />
      ) : (
        <>
          <p className="small">
            {state.data.total
              ? `${offset + 1}–${Math.min(offset + 20, state.data.total)}`
              : "0"}{" "}
            of {state.data.total} trials
          </p>
          <ul className="catalog-list">
            {state.data.items.map((trial) => (
              <li key={trial.trial_id}>
                <div>
                  <span className="eyebrow">
                    {trial.trial_id} · {words(trial.source_kind)}
                  </span>
                  <h3>
                    <button
                      className="title-button"
                      onClick={() => openTrial(trial.trial_id)}
                    >
                      {trial.title || trial.trial_id}
                    </button>
                  </h3>
                </div>
                <button
                  onClick={() => openTrial(trial.trial_id)}
                  aria-label={`View trial ${trial.trial_id}`}
                >
                  Read detail
                </button>
              </li>
            ))}
          </ul>
          <div className="pagination">
            <button
              disabled={offset === 0}
              onClick={() => setOffset((n) => Math.max(0, n - 20))}
            >
              Previous trials
            </button>
            <button
              disabled={offset + 20 >= state.data.total}
              onClick={() => setOffset((n) => n + 20)}
            >
              Next trials
            </button>
          </div>
        </>
      )}
    </section>
  );
}
