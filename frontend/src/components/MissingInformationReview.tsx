import type { ReviewPlan } from "../api/reviewContracts";
import { JsonEvidence, words } from "./Common";

export function MissingInformationReview({
  plan,
}: {
  plan?: ReviewPlan | null;
}) {
  if (!plan)
    return (
      <p className="small">
        No review ordering was recorded in this historical packet. Opening it
        does not compute a new plan.
      </p>
    );
  const blockers = plan.basis.filter((b) => b.blocking_ids.length);
  return (
    <section className="evidence-panel" aria-label="Missing information review">
      <h2>Prioritised information review</h2>
      <p className="notice">
        Research worklist only: review existing synthetic records, not clinical
        urgency or advice to order tests. Ordering favours reuse across
        unresolved source criteria. No value is inferred and no screening
        outcome changes. One item may not resolve the whole trial.
      </p>
      <p className="small">
        {plan.mode === "grouped"
          ? "Uses the separate grouped interpretation."
          : "Uses ordinary deterministic screening."}{" "}
        Only the selected case–trial pair is included here.
      </p>
      {blockers.length > 0 && (
        <p className="notice">
          Existing likely exclusion blockers remain in place. Reviewing missing
          information does not remove them.
        </p>
      )}
      {plan.basis.some((b) => b.scope_review_required) && (
        <p className="notice">
          Resolve shared scope or criterion interpretation before treating local
          fact gaps as active questions.
        </p>
      )}
      {!plan.items.length && (
        <p>
          No active fact-review items were identified by these bounded rules.
          This does not establish complete information or eligibility.
        </p>
      )}
      <ol className="criteria-list">
        {plan.items.map((item) => (
          <li key={item.item_id}>
            <h3>
              {item.rank}. Verify {words(item.fact_name)}
              {item.requested_unit ? ` (${item.requested_unit})` : ""}
            </h3>
            <p>{item.prompt}</p>
            <p className="small">
              Linked source criteria: {item.criterion_count} · Trials:{" "}
              {item.trial_count} · Without existing blockers:{" "}
              {item.unblocked_trial_count}. These are counts, not expected
              benefit or probabilities.
            </p>
            <details className="source-field">
              <summary>Why this item is listed</summary>
              {item.references.map((r) => (
                <div key={r.reference_id}>
                  <blockquote>{r.evidence.text}</blockquote>
                  <p className="small">
                    {words(r.reason)} · characters {r.evidence.start}–
                    {r.evidence.end} · {r.trial_id}
                  </p>
                </div>
              ))}
            </details>
          </li>
        ))}
      </ol>
      <details
        className="source-field"
        open={plan.interpretation_reviews.length > 0}
      >
        <summary>
          Criterion interpretation first ({plan.interpretation_reviews.length})
        </summary>
        <p className="small">
          Unsupported wording, uncertain scope or another interpretation
          limitation. These are not requests for additional patient facts.
        </p>
        {plan.interpretation_reviews.map((r) => (
          <div key={r.reference_id}>
            <blockquote>{r.evidence.text}</blockquote>
            <p className="small">
              {words(r.reason)} · source characters {r.evidence.start}–
              {r.evidence.end}
            </p>
          </div>
        ))}
      </details>
      <details className="source-field">
        <summary>
          Unknowns in settled logic branches (
          {plan.settled_branch_reviews.length})
        </summary>
        <p className="small">
          Retained for traceability. The enclosing expression is already
          determined, so these are not prioritised as active questions.
        </p>
        {plan.settled_branch_reviews.map((r) => (
          <blockquote key={r.reference_id}>{r.evidence.text}</blockquote>
        ))}
      </details>
      <JsonEvidence
        value={plan}
        label="Review ordering and source provenance"
      />
    </section>
  );
}
