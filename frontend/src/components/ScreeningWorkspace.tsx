import { useState } from "react";
import { workbench } from "../api/workbench";
import type { Screening } from "../api/workbenchContracts";
import { useResource } from "../hooks/useResource";
import { useOperation } from "../hooks/useOperation";
import { ErrorPanel, JsonEvidence, Loading } from "./Common";
import { EvidencePanel } from "./EvidencePanel";
import { GroupedEvidence } from "./GroupedEvidence";

export function ScreeningWorkspace({
  caseId,
  initialTrial = "",
  openTrial,
}: {
  caseId: string;
  initialTrial?: string;
  openTrial: (id: string) => void;
}) {
  const { state, retry } = useResource(workbench.trialChoices);
  const [trial, setTrial] = useState(initialTrial),
    [semantic, setSemantic] = useState(false);
  const [grouped, setGrouped] = useState(false);
  const run = useOperation<Screening>();
  const submit = () =>
    run.run((signal) =>
      grouped
        ? workbench.screen(caseId, trial, semantic, signal, true)
        : workbench.screen(caseId, trial, semantic, signal),
    );
  return (
    <div className="panel">
      <h2>Screen a case–trial pair</h2>
      <p className="muted">
        Inspect full criteria, supporting facts, blockers and unknowns. This
        does not modify retrieval or determine clinical eligibility.
      </p>
      {state.status === "loading" ? (
        <Loading label="Loading verified trial choices…" />
      ) : state.status === "error" ? (
        <ErrorPanel message={state.message} retry={retry} />
      ) : (
        <form
          className="workbench-form"
          onSubmit={(e) => {
            e.preventDefault();
            void submit();
          }}
        >
          <label>
            Trial to screen
            <select
              value={trial}
              disabled={run.busy}
              onChange={(e) => {
                setTrial(e.target.value);
                run.reset();
              }}
            >
              <option value="">Select a trial</option>
              {state.data.map((t) => (
                <option key={t.trial_id} value={t.trial_id}>
                  {t.trial_id} · {t.title}
                </option>
              ))}
            </select>
          </label>
          <label className="checkbox-label">
            <input
              type="checkbox"
              checked={semantic}
              disabled={run.busy}
              onChange={(e) => {
                setSemantic(e.target.checked);
                run.reset();
              }}
            />
            Include optional learned NLI advisories (never promoted)
          </label>
          <div className="button-row">
            <label className="checkbox-label">
              <input
                type="checkbox"
                checked={grouped}
                disabled={run.busy}
                onChange={(e) => {
                  setGrouped(e.target.checked);
                  run.reset();
                }}
              />
              Compare experimental grouped eligibility logic
            </label>
            <button
              className="primary"
              disabled={
                run.busy || !state.data.some((t) => t.trial_id === trial)
              }
            >
              {run.busy ? "Screening…" : "Screen selected pair"}
            </button>
            <button
              type="button"
              disabled={!trial}
              onClick={() => openTrial(trial)}
            >
              Read original trial
            </button>
          </div>
        </form>
      )}
      {run.busy && <Loading label="Checking complete source criteria…" />}
      {run.error && (
        <ErrorPanel message={run.error} retry={() => void submit()} />
      )}
      {run.data && (
        <>
          <p className="badge neutral">
            {run.data.replayed ? "Saved replay" : "Newly computed"} ·{" "}
            {run.data.operation_id.slice(0, 12)}
          </p>
          <p className="small">
            A saved replay is historical evidence, not fresh inference.
          </p>
          {run.data.result.grouped && (
            <GroupedEvidence
              grouped={run.data.result.grouped}
              assessment={run.data.result.assessment}
            />
          )}
          <EvidencePanel
            assessment={run.data.result.assessment}
            semantic={run.data.result.semantic}
          />
          <JsonEvidence value={run.data} label="Screening operation identity" />
        </>
      )}
    </div>
  );
}
