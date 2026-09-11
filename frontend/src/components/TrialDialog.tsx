import { useCallback, useEffect, useRef } from "react";
import { api } from "../api/client";
import type { Trial } from "../api/contracts";
import { useResource } from "../hooks/useResource";
import { ErrorPanel, JsonEvidence, Loading, words } from "./Common";

function TrialContent({ trial }: { trial: Trial }) {
  const parsed = trial.criteria;
  const byId = new Map(parsed.criteria.map((c) => [c.criterion_id, c]));
  return (
    <>
      <p className="eyebrow">
        {words(trial.evidence.source_kind)} · {trial.evidence.trial_id}
      </p>
      <h2>
        {trial.evidence.fields.brief_title?.normalized ||
          trial.evidence.trial_id}
      </h2>
      <p className="notice">
        Historical or invented research source. This view does not establish
        current recruitment or medical eligibility.
      </p>
      <h3>Trial source fields</h3>
      {Object.entries(trial.evidence.fields).map(([name, field]) => (
        <details
          className="source-field"
          key={name}
          open={name === "brief_summary"}
        >
          <summary>{words(name)}</summary>
          <p className="preserve">
            {field.normalized || "Not supplied in this source field."}
          </p>
          <JsonEvidence
            value={field}
            label="Original text and source locator"
          />
        </details>
      ))}
      <div className="section-heading">
        <h3>Parsed criteria</h3>
        <span className="count">{parsed.criteria.length}</span>
      </div>
      <p className="muted">
        Conservative parsing only—not a patient–criterion assessment. Read the
        complete section and parent context before interpreting a clause.
      </p>
      {parsed.issues.length > 0 && (
        <ul className="notice">
          {parsed.issues.map((issue, i) => (
            <li key={i}>{words(issue)}</li>
          ))}
        </ul>
      )}
      {parsed.criteria.length === 0 && (
        <p>
          No supported criterion records were parsed. The original source
          remains available below.
        </p>
      )}
      <ol className="criteria-list">
        {parsed.criteria.map((criterion) => (
          <li key={criterion.criterion_id}>
            <div className="tags">
              <span>Criterion {criterion.ordinal}</span>
              <span>{words(criterion.section)}</span>
              <span>{criterion.types.map(words).join(", ")}</span>
            </div>
            {criterion.parent_id && (
              <p className="parent-context">
                <strong>Parent context: </strong>
                {byId.get(criterion.parent_id)?.evidence.text ??
                  "See full source for parent context."}
              </p>
            )}
            <blockquote>{criterion.evidence.text}</blockquote>
            <p className="small muted">
              Logic: {words(criterion.logic)} · characters{" "}
              {criterion.evidence.start}–{criterion.evidence.end}
            </p>
            {criterion.review_reasons.length > 0 && (
              <p className="review-note">
                Requires review:{" "}
                {criterion.review_reasons.map(words).join("; ")}
              </p>
            )}
            <JsonEvidence
              value={criterion}
              label="Criterion identity and parse record"
            />
          </li>
        ))}
      </ol>
      <details className="source-field">
        <summary>Complete original eligibility wording</summary>
        <pre>{parsed.source.text || "No eligibility wording supplied."}</pre>
      </details>
      <p className="small muted">
        Parser: {parsed.parser_version}
        <br />
        Source locator: {parsed.source.source_locator}
      </p>
      <JsonEvidence
        value={trial}
        label="Complete trial and parser provenance"
      />
    </>
  );
}
export function TrialDialog({ id, close }: { id: string; close: () => void }) {
  const ref = useRef<HTMLDialogElement>(null);
  const opener = useRef(document.activeElement);
  const load = useCallback(
    (signal: AbortSignal) => api.trial(id, signal),
    [id],
  );
  const { state, retry } = useResource(load);
  useEffect(() => {
    const dialog = ref.current!;
    dialog.showModal();
    return () => {
      dialog.close();
      if (opener.current instanceof HTMLElement && opener.current.isConnected)
        opener.current.focus();
    };
  }, []);
  return (
    <dialog
      ref={ref}
      aria-labelledby="trial-dialog-title"
      onCancel={(event) => {
        event.preventDefault();
        close();
      }}
    >
      <div className="dialog-header">
        <strong id="trial-dialog-title">Trial & criterion detail · {id}</strong>
        <button onClick={close} autoFocus>
          Close detail
        </button>
      </div>
      <div className="dialog-body">
        {state.status === "loading" ? (
          <Loading label="Loading verified trial evidence…" />
        ) : state.status === "error" ? (
          <ErrorPanel message={state.message} retry={retry} />
        ) : (
          <TrialContent trial={state.data} />
        )}
      </div>
    </dialog>
  );
}
