import type { Grouped, LogicNode } from "../api/groupedContracts";
import type { Assessment } from "../api/workbenchContracts";
import { JsonEvidence, StatusBadge, words } from "./Common";

export function GroupedEvidence({
  grouped: g,
  assessment: a,
}: {
  grouped: Grouped;
  assessment: Assessment;
}) {
  const facts = new Map(a.profile.facts.map((f) => [f.fact_id, f]));
  const show = (n: LogicNode) => (
    <li key={n.node_id}>
      <details className="source-field" open={n.children.length > 0}>
        <summary>
          {words(n.operator)} · predicate {n.truth}
        </summary>
        <blockquote>{n.evidence.text}</blockquote>
        <p className="small">
          {words(n.reason)} · source characters {n.evidence.start}–
          {n.evidence.end}
        </p>
        {!n.children.length &&
          n.fact_ids.map((id) => (
            <p className="small" key={id}>
              Cited synthetic fact: {facts.get(id)?.evidence.text}
            </p>
          ))}
        {n.children.length > 0 && <ul>{n.children.map(show)}</ul>}
      </details>
    </li>
  );
  return (
    <section aria-label="Grouped eligibility logic">
      <div className="section-heading">
        <h2>Grouped screening · experimental</h2>
        <StatusBadge status={g.status} />
      </div>
      <p className="notice">
        Separate opt-in deterministic interpretation. True/false describe
        predicates; an exclusion predicate being true is a likely blocker. A
        false OR branch alone is not a blocker. Ordinary screening below is
        unchanged. Requires professional review.
      </p>
      {g.scope_review_required && (
        <p className="notice">
          Unresolved shared scope: all section conclusions remain unknown. Local
          predicate values below are not trial decisions.
        </p>
      )}
      {g.sections.map((s) => (
        <section key={s.ordinal}>
          <h3>
            {words(s.section)} · section predicate {s.root.truth}
          </h3>
          <ul>{show(s.root)}</ul>
        </section>
      ))}
      <JsonEvidence
        value={g}
        label="Complete grouped logic and source provenance"
      />
    </section>
  );
}
