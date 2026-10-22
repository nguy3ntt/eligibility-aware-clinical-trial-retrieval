import { passageRankingSchema } from "../api/contracts";
import { words } from "./Common";

export function PassageEvidence({ ranking }: { ranking: unknown }) {
  const parsed = passageRankingSchema.safeParse(ranking);
  if (!parsed.success) return null;
  return (
    <details className="source-field">
      <summary>Contributing fields and passages</summary>
      <p className="small">
        Best passage per field, fused by trial rank. Similarity is not
        eligibility or causal model attribution.
      </p>
      {Object.entries(parsed.data.branches).map(([name, branch]) => (
        <section key={name}>
          <h4>
            {words(name)} · field rank {branch.rank}
          </h4>
          <p className="small">
            Cosine {branch.raw_score.toFixed(4)} · RRF contribution{" "}
            {branch.rrf_contribution.toFixed(6)}
          </p>
          <blockquote className="preserve">{branch.segment.text}</blockquote>
          <p className="small muted">
            {branch.segment.locator}
            {branch.segment.original_item !== null &&
              ` · item ${branch.segment.original_item + 1} · characters ${branch.segment.start}–${branch.segment.end}`}
          </p>
        </section>
      ))}
    </details>
  );
}
