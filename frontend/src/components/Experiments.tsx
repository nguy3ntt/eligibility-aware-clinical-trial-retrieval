import { useCallback, useState } from "react";
import { workbench } from "../api/workbench";
import type { FixtureExperiment } from "../api/workbenchContracts";
import { useResource } from "../hooks/useResource";
import { useOperation } from "../hooks/useOperation";
import { ErrorPanel, Loading, words } from "./Common";
import { OperationView } from "./OperationView";

function SavedOperation({
  id,
  openTrial,
}: {
  id: string;
  openTrial: (id: string) => void;
}) {
  const load = useCallback(
    (signal: AbortSignal) => workbench.operation(id, signal),
    [id],
  );
  const { state, retry } = useResource(load);
  return state.status === "loading" ? (
    <Loading label="Loading stored operation…" />
  ) : state.status === "error" ? (
    <ErrorPanel message={state.message} retry={retry} />
  ) : (
    <OperationView operation={state.data} openTrial={openTrial} />
  );
}
export function Experiments({
  openTrial,
}: {
  openTrial: (id: string) => void;
}) {
  const [offset, setOffset] = useState(0),
    [selected, setSelected] = useState(""),
    [lookup, setLookup] = useState("");
  const load = useCallback(
    (signal: AbortSignal) => workbench.operations(offset, signal),
    [offset],
  );
  const { state, retry } = useResource(load);
  const experiment = useOperation<FixtureExperiment>();
  const run = () =>
    experiment.run(async (signal) => {
      const result = await workbench.experiment(signal);
      signal.throwIfAborted();
      retry();
      setSelected(result.operation_id);
      return result;
    });
  return (
    <div className="panel">
      <h2>Experiments & saved operations</h2>
      <p className="muted">
        Inspect versioned search/screening runs and imported historical reports.
        The list uses stable operation-ID order, not chronological order.
      </p>
      <div className="notice">
        <strong>One bounded evaluation is available</strong>
        <p>
          Run the existing authored screening fixtures. No arbitrary jobs,
          benchmark retuning or automatic model promotion.
        </p>
        <button
          className="primary"
          disabled={experiment.busy}
          onClick={() => void run()}
        >
          {experiment.busy
            ? "Evaluating…"
            : "Run authored screening evaluation"}
        </button>
      </div>
      {experiment.error && (
        <ErrorPanel message={experiment.error} retry={() => void run()} />
      )}
      {experiment.busy && (
        <Loading label="Checking invented screening fixtures…" />
      )}
      {experiment.data && (
        <p role="status">
          Evaluation {experiment.data.result.status}:{" "}
          {experiment.data.result.evaluation.exact_pairs}/
          {experiment.data.result.evaluation.pairs} exact pairs;{" "}
          {experiment.data.result.evaluation.criterion_count} criteria.{" "}
          {experiment.data.replayed ? "Saved replay." : "Newly computed."}
        </p>
      )}
      <form
        className="operation-lookup"
        onSubmit={(e) => {
          e.preventDefault();
          if (/^[a-f0-9]{64}$/.test(lookup)) setSelected(lookup);
        }}
      >
        <label>
          Saved operation ID
          <input
            value={lookup}
            onChange={(e) => setLookup(e.target.value)}
            pattern="[a-f0-9]{64}"
            maxLength={64}
            required
            autoComplete="off"
            spellCheck={false}
            placeholder="64-character operation hash only"
          />
        </label>
        <button>Open saved operation</button>
      </form>
      <button onClick={retry}>Refresh saved operations</button>
      {state.status === "loading" ? (
        <Loading label="Loading saved operations…" />
      ) : state.status === "error" ? (
        <ErrorPanel message={state.message} retry={retry} />
      ) : (
        <>
          <p className="small">
            {state.data.total
              ? `${offset + 1}–${Math.min(offset + 20, state.data.total)}`
              : "0"}{" "}
            of {state.data.total} saved operations
          </p>
          {!state.data.total && (
            <p>
              No saved operations yet. Run a search, screening or authored
              evaluation.
            </p>
          )}
          <ul className="operation-list">
            {state.data.items.map((p) => (
              <li key={p.operation_id}>
                <button
                  aria-label={`Open ${p.operation_id}`}
                  aria-pressed={selected === p.operation_id}
                  onClick={() => setSelected(p.operation_id)}
                >
                  <span>{words(p.kind)}</span>
                  <code>{p.operation_id}</code>
                </button>
              </li>
            ))}
          </ul>
          <div className="pagination">
            <button
              disabled={offset === 0}
              onClick={() => setOffset((n) => Math.max(0, n - 20))}
            >
              Previous operations
            </button>
            <button
              disabled={offset + 20 >= state.data.total}
              onClick={() => setOffset((n) => n + 20)}
            >
              Next operations
            </button>
          </div>
        </>
      )}
      {selected && (
        <div className="selected-operation">
          <SavedOperation key={selected} id={selected} openTrial={openTrial} />
        </div>
      )}
    </div>
  );
}
