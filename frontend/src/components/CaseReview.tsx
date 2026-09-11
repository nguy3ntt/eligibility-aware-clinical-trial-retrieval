import type { Profile } from "../api/contracts";
import { JsonEvidence, words } from "./Common";

export function CaseReview({ profile }: { profile: Profile }) {
  return (
    <section aria-labelledby="case-review-title" className="case-review">
      <div className="section-heading">
        <h2 id="case-review-title">Synthetic case</h2>
        <span className="badge neutral">Read only</span>
      </div>
      <p className="eyebrow">{profile.case.case_id}</p>
      <p className="narrative">{profile.case.text}</p>
      <details open className="fact-review">
        <summary>
          Extracted facts <span className="count">{profile.facts.length}</span>
        </summary>
        <p className="muted small">
          Bounded deterministic extraction, not a complete clinical profile.
          Reviewing facts does not edit them or change the legacy search
          filters.
        </p>
        {profile.facts.length === 0 && (
          <p>
            No supported facts were extracted. Missing information is not a
            negative finding.
          </p>
        )}
        {profile.facts.map((fact) => (
          <article className="fact" key={fact.fact_id}>
            <div className="fact-heading">
              <strong>{words(fact.name)}</strong>
              <span className="muted small">{words(fact.kind)}</span>
            </div>
            <p className="fact-value">
              {fact.operator !== "eq" ? `${words(fact.operator)} ` : ""}
              {typeof fact.value === "string" ? words(fact.value) : fact.value}
              {fact.unit ? ` ${fact.unit}` : ""}
            </p>
            <div className="tags">
              {[
                fact.assertion,
                fact.temporality,
                `${fact.experiencer} experiencer`,
                `${fact.certainty} certainty`,
              ].map((tag) => (
                <span key={tag}>{words(tag)}</span>
              ))}
            </div>
            <details>
              <summary>Source evidence</summary>
              <blockquote>{fact.evidence.text}</blockquote>
              <p className="small">
                Character span {fact.evidence.start}–{fact.evidence.end}. Rule:{" "}
                {fact.rule_id}
              </p>
              <p className="small">Full context: {fact.context.text}</p>
            </details>
          </article>
        ))}
      </details>
      <div className="notice">
        <strong>Information not extracted</strong>
        <p>
          {profile.missing_categories.length
            ? profile.missing_categories.map(words).join(", ")
            : "No missing supported categories; coverage is still not exhaustive."}
        </p>
        <p className="small">
          Unmentioned information never means a criterion is satisfied.
        </p>
      </div>
      {profile.issues.length > 0 && (
        <details className="notice">
          <summary>Extraction review notes ({profile.issues.length})</summary>
          <ul>
            {profile.issues.map((issue, i) => (
              <li key={i}>{issue.message}</li>
            ))}
          </ul>
        </details>
      )}
      <p className="muted small">
        Source: {profile.case.source} · {profile.case.source_locator}
        <br />
        Extractor: {profile.extractor_version}
      </p>
      <JsonEvidence value={profile} label="Full profile and provenance" />
    </section>
  );
}
