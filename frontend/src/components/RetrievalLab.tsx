import { useState } from "react";
import {
  assertComparable,
  defaults,
  workbench,
  type RetrievalOptions,
} from "../api/workbench";
import type { Search } from "../api/contracts";
import { useOperation } from "../hooks/useOperation";
import { ErrorPanel, JsonEvidence, Loading } from "./Common";
import { Results } from "./Results";

type Timed = { packet: Search; seconds: number };
type Comparison = { baseline: Timed; candidate: Timed };
export function RetrievalLab({
  caseId,
  openTrial,
}: {
  caseId: string;
  openTrial: (id: string) => void;
}) {
  const [options, setOptions] = useState<RetrievalOptions>({
    ...defaults,
    method: "hybrid",
  });
  const run = useOperation<Comparison>();
  const change = (patch: Partial<RetrievalOptions>) => {
    setOptions((o) => ({ ...o, ...patch }));
    run.reset();
  };
  const submit = () =>
    run.run(async (signal) => {
      const timed = async (config: RetrievalOptions) => {
        const start = performance.now();
        const packet = await workbench.retrieve(caseId, config, signal);
        return { packet, seconds: (performance.now() - start) / 1000 };
      };
      const baseline = await timed({ ...defaults, top_k: options.top_k });
      if (signal.aborted) throw new DOMException("Cancelled", "AbortError");
      const candidate = await timed(options);
      assertComparable(baseline.packet, candidate.packet);
      return { baseline, candidate };
    });
  return (
    <section className="panel">
      <h2>Retrieval laboratory</h2>
      <p className="muted">
        Compare one candidate configuration against exact dense + legacy
        age/sex. Requests run sequentially; the ordinary search defaults never
        change.
      </p>
      <p className="notice">
        Single-case exploration, not a benchmark. BM25, cosine, fusion and
        cross-encoder scores are incompatible scales. No clinical probability,
        nDCG or ANN recall is inferred from this comparison.
      </p>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          void submit();
        }}
      >
        <fieldset disabled={run.busy} className="lab-options">
          <legend>Candidate configuration</legend>
          <label>
            Retrieval method
            <select
              value={options.method}
              onChange={(e) =>
                change({ method: e.target.value as RetrievalOptions["method"] })
              }
            >
              <option value="dense">Exact dense</option>
              <option value="sparse">BM25 sparse</option>
              <option value="hybrid">Hybrid · RRF</option>
            </select>
          </label>
          <label>
            Metadata filter
            <select
              value={options.filter}
              onChange={(e) =>
                change({ filter: e.target.value as RetrievalOptions["filter"] })
              }
            >
              <option value="age_sex">Age / sex</option>
              <option value="none">No metadata filter</option>
            </select>
          </label>
          <label>
            Fact extractor
            <select
              value={options.fact_extractor}
              onChange={(e) =>
                change({
                  fact_extractor: e.target
                    .value as RetrievalOptions["fact_extractor"],
                })
              }
            >
              <option value="legacy">Legacy</option>
              <option value="profile">Evidence-backed profile</option>
            </select>
          </label>
          <label>
            Displayed depth
            <select
              value={options.top_k}
              onChange={(e) => change({ top_k: Number(e.target.value) })}
            >
              {[3, 5, 10].map((n) => (
                <option key={n}>{n}</option>
              ))}
            </select>
          </label>
          <label className="checkbox-label">
            <input
              type="checkbox"
              checked={options.rerank}
              onChange={(e) => change({ rerank: e.target.checked })}
            />
            Opt into cross-encoder reranking
          </label>
          <label>
            Reranked prefix
            <select
              disabled={!options.rerank || run.busy}
              value={options.rerank_depth}
              onChange={(e) => change({ rerank_depth: Number(e.target.value) })}
            >
              {[10, 20].map((n) => (
                <option key={n}>{n}</option>
              ))}
            </select>
          </label>
        </fieldset>
        <button className="primary" disabled={run.busy}>
          {run.busy ? "Comparing…" : "Run comparison"}
        </button>
      </form>
      {run.busy && (
        <Loading label="Running baseline, then candidate configuration…" />
      )}
      {run.error && (
        <ErrorPanel message={run.error} retry={() => void submit()} />
      )}
      {run.data && <ComparisonView value={run.data} openTrial={openTrial} />}
    </section>
  );
}
function ComparisonView({
  value,
  openTrial,
}: {
  value: Comparison;
  openTrial: (id: string) => void;
}) {
  const a = value.baseline.packet.result.results,
    b = value.candidate.packet.result.results;
  const ids = [...new Set([...a, ...b].map((r) => r.trial_id))];
  return (
    <div className="comparison">
      <h3>Observed ranking comparison</h3>
      <p className="small">
        Top-{value.candidate.packet.request.top_k} overlap:{" "}
        {a.filter((r) => b.some((s) => s.trial_id === r.trial_id)).length}{" "}
        shared trials. Absence here means absent from the displayed prefix, not
        the full candidate set.
      </p>
      <div className="table-scroll">
        <table>
          <caption>Ranks only—scores are not subtracted or combined</caption>
          <thead>
            <tr>
              <th>Trial</th>
              <th>Baseline rank</th>
              <th>Candidate rank</th>
            </tr>
          </thead>
          <tbody>
            {ids.map((id) => (
              <tr key={id}>
                <td>
                  <button
                    className="title-button"
                    onClick={() => openTrial(id)}
                  >
                    {id}
                  </button>
                </td>
                <td>
                  {a.find((r) => r.trial_id === id)?.relevance.ranking.rank ??
                    "Not displayed"}
                </td>
                <td>
                  {b.find((r) => r.trial_id === id)?.relevance.ranking.rank ??
                    "Not displayed"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="notice">
        Browser round trip: baseline {value.baseline.seconds.toFixed(2)} s (
        {value.baseline.packet.replayed ? "saved replay" : "computed"});
        candidate {value.candidate.seconds.toFixed(2)} s (
        {value.candidate.packet.replayed ? "saved replay" : "computed"}).
        Includes transfer, source validation and persistence; cached and fresh
        timings are not comparable model latency.
      </p>
      <details open>
        <summary>Candidate results and score provenance</summary>
        <Results search={value.candidate.packet} openTrial={openTrial} />
      </details>
      <details>
        <summary>Baseline results and evidence</summary>
        <Results search={value.baseline.packet} openTrial={openTrial} />
      </details>
      <JsonEvidence
        value={{
          baseline: value.baseline.packet.provenance,
          candidate: value.candidate.packet.provenance,
        }}
        label="Matched source, code and runtime identities"
      />
    </div>
  );
}
