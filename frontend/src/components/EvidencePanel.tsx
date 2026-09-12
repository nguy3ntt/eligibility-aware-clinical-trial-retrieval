import type { Assessment, Semantic } from "../api/workbenchContracts";
import { JsonEvidence, StatusBadge, words } from "./Common";

export function EvidencePanel({
  assessment: a,
  semantic = null,
}: {
  assessment: Assessment;
  semantic?: Semantic | null;
}) {
  const facts = new Map(a.profile.facts.map((f) => [f.fact_id, f]));
  const criteria = new Map(a.parsed.criteria.map((c) => [c.criterion_id, c]));
  const advisories = new Map(
    semantic?.advisories.map((n) => [n.criterion_id, n]),
  );
  return (
    <section className="evidence-panel" aria-label="Eligibility evidence">
      <div className="section-heading">
        <h2>Eligibility evidence</h2>
        <StatusBadge status={a.status} />
      </div>
      <p className="small">
        Case <strong>{a.profile.case.case_id}</strong> · Trial{" "}
        <strong>{a.parsed.source.trial_id}</strong>
      </p>
      <p className="notice">
        Deterministic research screening only. Requires professional review.
        Missing or unsupported information never satisfies a criterion.
      </p>
      <div className="stat-grid">
        <div>
          <strong>{a.criteria.length}</strong>
          <span>Criteria retained</span>
        </div>
        <div>
          <strong>{a.blocking_criterion_ids.length}</strong>
          <span>Likely exclusion blockers</span>
        </div>
        <div>
          <strong>{a.unknown_criterion_ids.length}</strong>
          <span>Unknown outcomes</span>
        </div>
      </div>
      <div className="notice">
        <strong>Missing information</strong>
        <p>
          {a.missing_information.length
            ? a.missing_information.map(words).join("; ")
            : "No missing items were reported by these bounded rules. This does not establish clinical completeness."}
        </p>
      </div>
      <details className="source-field">
        <summary>Complete case and trial context</summary>
        <h3>Synthetic narrative</h3>
        <p className="preserve">{a.profile.case.text}</p>
        <h3>Original eligibility wording</h3>
        <pre>{a.parsed.source.text}</pre>
        <p className="small">Source: {a.parsed.source.source_locator}</p>
      </details>
      <ol className="criteria-list">
        {a.criteria.map((decision, i) => {
          const criterion = a.parsed.criteria[i],
            advisory = advisories.get(decision.criterion_id);
          const ancestors = [];
          const seen = new Set<string>();
          let parent = criterion.parent_id;
          while (parent && !seen.has(parent)) {
            seen.add(parent);
            const c = criteria.get(parent);
            if (!c) break;
            ancestors.unshift(c.evidence.text);
            parent = c.parent_id;
          }
          return (
            <li key={decision.criterion_id}>
              <div className="section-heading">
                <h3>
                  Criterion {criterion.ordinal} · {words(criterion.section)}
                </h3>
                <span className={`badge ${decision.outcome}`}>
                  {words(decision.outcome)}
                </span>
              </div>
              {ancestors.map((text, n) => (
                <p className="parent-context" key={n}>
                  <strong>Ancestor context: </strong>
                  {text}
                </p>
              ))}
              <blockquote>{decision.evidence.text}</blockquote>
              <p>
                <strong>Rule explanation: </strong>
                {words(decision.reason)}
              </p>
              <p className="small muted">
                Deterministic rule · {decision.rule_id} · source characters{" "}
                {decision.evidence.start}–{decision.evidence.end}
              </p>
              {criterion.review_reasons.length > 0 && (
                <p className="review-note">
                  Parser review:{" "}
                  {criterion.review_reasons.map(words).join("; ")}
                </p>
              )}
              <h4>Synthetic fact evidence</h4>
              {!decision.fact_ids.length && (
                <p className="small">
                  No supporting fact was cited. This is not evidence of
                  satisfying the criterion.
                </p>
              )}
              {decision.fact_ids.map((id) => {
                const f = facts.get(id)!;
                return (
                  <div className="cited-fact" key={id}>
                    <strong>{words(f.name)}</strong>
                    <div className="tags">
                      {[
                        f.assertion,
                        f.temporality,
                        f.certainty,
                        f.experiencer,
                      ].map((tag, n) => (
                        <span key={n}>{words(tag)}</span>
                      ))}
                    </div>
                    <blockquote>{f.evidence.text}</blockquote>
                    <p className="small">Context: {f.context.text}</p>
                    <p className="small muted">
                      Characters {f.evidence.start}–{f.evidence.end} ·{" "}
                      {f.rule_id}
                    </p>
                  </div>
                );
              })}
              {decision.missing_information.length > 0 && (
                <p className="notice">
                  Missing: {decision.missing_information.map(words).join("; ")}
                </p>
              )}
              {advisory && (
                <aside className="learned-advisory">
                  <strong>Learned NLI advisory · NOT PROMOTED</strong>
                  <p className="small">
                    {words(advisory.status)} · proposed{" "}
                    {words(advisory.proposed_outcome)}
                    {advisory.reason ? ` · ${words(advisory.reason)}` : ""}
                  </p>
                  <p className="small">
                    Text-relation outputs only. They never change the
                    deterministic outcome above or represent clinical
                    eligibility probabilities.
                  </p>
                  {advisory.probabilities && (
                    <dl className="probabilities">
                      {Object.entries(advisory.probabilities).map(
                        ([label, value]) => (
                          <div key={label}>
                            <dt>{label}</dt>
                            <dd>{value.toFixed(4)}</dd>
                          </div>
                        ),
                      )}
                    </dl>
                  )}
                  <JsonEvidence
                    value={advisory}
                    label="Full advisory input and output"
                  />
                </aside>
              )}
              <JsonEvidence
                value={{ criterion, decision }}
                label="Criterion and decision provenance"
              />
            </li>
          );
        })}
      </ol>
      {semantic && (
        <JsonEvidence
          value={semantic.model}
          label="Advisory model identity and limits"
        />
      )}
      <p className="small muted">
        Verifier: {a.verifier_version} · Parser: {a.parsed.parser_version}
      </p>
      <JsonEvidence
        value={a}
        label="Full deterministic assessment and provenance"
      />
    </section>
  );
}
