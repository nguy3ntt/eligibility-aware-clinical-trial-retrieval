import { caseId, hash, profile, search, trial, trialId } from "./fixtures";
import type {
  Assessment,
  FixtureExperiment,
  Screening,
} from "../api/workbenchContracts";

export const assessment: Assessment = {
  schema_version: "research-screening-v1",
  assessment_id: hash,
  verifier_version: "invented-verifier",
  verifier_sha256: hash,
  profile,
  parsed: trial.criteria,
  criteria: [
    {
      criterion_id: hash,
      outcome: "unknown",
      reason: "unsupported_invented_rule",
      method: "deterministic_rule",
      rule_id: "invented-rule",
      fact_ids: [],
      evidence: trial.criteria.criteria[0].evidence,
      missing_information: ["invented_missing_measurement"],
      confidence: null,
    },
  ],
  status: "insufficient_information",
  blocking_criterion_ids: [],
  unknown_criterion_ids: [hash],
  missing_information: ["invented_missing_measurement"],
  requires_professional_review: true,
  notice: "Invented research only.",
};
export const screening: Screening = {
  schema_version: "research-api-v1",
  operation_id: hash,
  status: "complete",
  replayed: false,
  notice: "Invented research only.",
  provenance: search.provenance,
  kind: "screening",
  request: { case_id: caseId, trial_id: trialId, semantic: false },
  result: { assessment, explanation: {}, semantic: null },
};
export const fixtureExperiment: FixtureExperiment = {
  schema_version: "research-api-v1",
  operation_id: "b".repeat(64),
  status: "complete",
  replayed: false,
  notice: "Invented research only.",
  provenance: search.provenance,
  kind: "experiment",
  request: { configuration: "screening-fixtures-v1" },
  result: {
    configuration: "screening-fixtures-v1",
    clinical_validation: false,
    status: "passed",
    fixture_sha256: hash,
    evaluation: { pairs: 2, exact_pairs: 2, criterion_count: 1 },
  },
};
