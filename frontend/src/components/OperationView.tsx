import { z } from "zod";
import type { Operation } from "../api/workbenchContracts";
import { EvidencePanel } from "./EvidencePanel";
import { Results } from "./Results";
import { JsonEvidence, words } from "./Common";

const metrics = z.record(z.string(), z.record(z.string(), z.number().finite()));
export function OperationView({
  operation: p,
  openTrial,
}: {
  operation: Operation;
  openTrial: (id: string) => void;
}) {
  return (
    <section className="operation-view">
      <h2>
        {p.kind === "reviewed_experiment"
          ? "Historical experiment"
          : `Saved ${words(p.kind)}`}
      </h2>
      <p className="small mono" aria-label="Stored operation identity">
        {p.operation_id}
      </p>
      <p className="notice">
        Stored historical record. Opening this view does not rerun a model or
        update the evidence.
      </p>
      {p.kind === "search" ? (
        <Results search={{ ...p, replayed: true }} openTrial={openTrial} />
      ) : p.kind === "screening" ? (
        <EvidencePanel
          assessment={p.result.assessment}
          semantic={p.result.semantic}
        />
      ) : p.kind === "experiment" ? (
        <>
          <h3>Authored screening evaluation</h3>
          <div className="stat-grid">
            <div>
              <strong>{p.result.status}</strong>
              <span>Evaluation outcome</span>
            </div>
            <div>
              <strong>
                {p.result.evaluation.exact_pairs}/{p.result.evaluation.pairs}
              </strong>
              <span>Exact invented pairs</span>
            </div>
            <div>
              <strong>{p.result.evaluation.criterion_count}</strong>
              <span>Criteria checked</span>
            </div>
          </div>
          <p>
            Authored development fixtures, not held-out or clinical validation.
          </p>
          <p className="small mono">
            Fixture SHA-256: {p.result.fixture_sha256}
          </p>
        </>
      ) : (
        <Historical report={p.result} reportId={p.source.report_id} />
      )}
      <JsonEvidence
        value={p}
        label="Complete stored operation and provenance"
      />
    </section>
  );
}
function Historical({
  report,
  reportId,
}: {
  report: Record<string, unknown>;
  reportId: string;
}) {
  const parsed = metrics.safeParse(report.metrics);
  const promotion = z
    .object({ enabled: z.boolean(), reason: z.string() })
    .safeParse(report.promotion);
  const model = z
    .object({ repository: z.string(), revision: z.string() })
    .safeParse(report.model);
  const requested = ["ndcg_at_10", "precision_at_10", "recall_at_100", "mrr"];
  const columns = parsed.success
    ? requested.filter((k) =>
        Object.values(parsed.data).some((row) => k in row),
      )
    : [];
  return (
    <>
      <p className="eyebrow">{reportId}</p>
      <p className="notice">
        Historical, bounded diagnostic. TREC relevance judgments do not confirm
        medical eligibility. These metrics do not measure the current browser
        request. No method promotion is inferred.
      </p>
      {typeof report.limitations === "string" && (
        <p>
          <strong>Recorded limitations: </strong>
          {report.limitations}
        </p>
      )}
      {promotion.success && (
        <p>
          <strong>Recorded promotion: </strong>
          {promotion.data.enabled
            ? "enabled in this historical report"
            : "not enabled"}{" "}
          · {words(promotion.data.reason)}. This does not change current
          defaults.
        </p>
      )}
      {model.success && (
        <p className="small mono">
          Recorded model: {model.data.repository} · revision{" "}
          {model.data.revision}
        </p>
      )}
      {parsed.success && columns.length > 0 ? (
        <div className="table-scroll">
          <table>
            <caption>
              Recorded metrics—not recalculated or merged across reports
            </caption>
            <thead>
              <tr>
                <th>System</th>
                {columns.map((c) => (
                  <th key={c}>{words(c)}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {Object.entries(parsed.data).map(([system, row]) => (
                <tr key={system}>
                  <th>{system}</th>
                  {columns.map((c) => (
                    <td key={c}>
                      {row[c] === undefined
                        ? "Not recorded"
                        : row[c].toFixed(4)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p>
          No supported aggregate metric table is recorded. The complete manifest
          remains available below.
        </p>
      )}
      {[
        "limitations",
        "promotion",
        "model",
        "encoder",
        "contract",
        "comparisons",
      ]
        .filter((key) => key in report)
        .map((key) => (
          <JsonEvidence
            key={key}
            value={report[key]}
            label={`Recorded ${key}`}
          />
        ))}
    </>
  );
}
