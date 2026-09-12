import { expect, it, vi } from "vitest";
import {
  assessmentSchema,
  fixtureExperimentSchema,
  screeningSchema,
} from "./workbenchContracts";
import {
  assertComparable,
  defaults,
  validateRetrieval,
  workbench,
} from "./workbench";
import {
  assessment,
  fixtureExperiment,
  screening,
} from "../test/workbenchFixtures";
import { caseId, hash, search, trialId } from "../test/fixtures";
import { retrievalSchema } from "./contracts";

it("rejects missing comparison provenance instead of matching two absent contracts", () => {
  expect(
    retrievalSchema.safeParse({
      ...search,
      result: { ...search.result, contract: undefined },
    }).success,
  ).toBe(false);
  expect(
    retrievalSchema.safeParse({
      ...search,
      provenance: { ...search.provenance, runtime_versions: undefined },
    }).success,
  ).toBe(false);
});

it("rejects contradictory stored retrieval score meanings and summaries", () => {
  const packet = structuredClone(search);
  packet.result.results[0].relevance.ranking.score_kind = "bm25_lucene";
  expect(retrievalSchema.safeParse(packet).success).toBe(false);
  delete packet.result.results[0].relevance.ranking.score_kind;
  packet.result.results[0].screening.status = "potential_match";
  expect(retrievalSchema.safeParse(packet).success).toBe(false);
});

it("accepts a complete abstaining assessment with source alignment", () =>
  expect(assessmentSchema.safeParse(assessment).success).toBe(true));
it.each(["status", "blocking", "evidence", "facts", "missing"])(
  "rejects inconsistent screening %s",
  (kind) => {
    const a = structuredClone(assessment);
    if (kind === "status") a.status = "potential_match";
    if (kind === "blocking") a.blocking_criterion_ids = [hash];
    if (kind === "evidence") a.criteria[0].evidence.text = "Changed";
    if (kind === "facts") a.criteria[0].fact_ids = ["b".repeat(64)];
    if (kind === "missing") a.missing_information = [];
    expect(assessmentSchema.safeParse(a).success).toBe(false);
  },
);
it("rejects screening returned for another case", () =>
  expect(
    screeningSchema.safeParse({
      ...screening,
      request: { ...screening.request, case_id: "other" },
    }).success,
  ).toBe(false));
it("rejects promoted learned advice and mismatched criterion evidence", () => {
  const packet = {
    ...screening,
    request: { ...screening.request, semantic: true },
    result: {
      ...screening.result,
      semantic: {
        model: {},
        advisories: [
          {
            criterion_id: hash,
            method: "learned_nli",
            promoted: true,
            status: "scored",
            proposed_outcome: "satisfied",
            patient_evidence: assessment.profile.case.text,
            criterion_evidence: assessment.criteria[0].evidence,
          },
        ],
      },
    },
  };
  expect(screeningSchema.safeParse(packet).success).toBe(false);
  packet.result.semantic.advisories[0].promoted = false;
  packet.result.semantic.advisories[0].criterion_id = "b".repeat(64);
  expect(screeningSchema.safeParse(packet).success).toBe(false);
});
it("rejects contradictory authored evaluation status", () =>
  expect(
    fixtureExperimentSchema.safeParse({
      ...fixtureExperiment,
      result: { ...fixtureExperiment.result, status: "failed" },
    }).success,
  ).toBe(false));
it("withholds comparisons across changed sources", () =>
  expect(() =>
    assertComparable(search, {
      ...search,
      provenance: { ...search.provenance, catalog_sha256: "b".repeat(64) },
    }),
  ).toThrow("comparison withheld"));
it("compares fresh and JSONB replay provenance independently of object key order", () => {
  const a = structuredClone(search);
  const b = structuredClone(search);
  a.result.contract = {
    model: { revision: "pinned", fields: ["title", "conditions"] },
    documents: 443,
  };
  b.result.contract = {
    documents: 443,
    model: { fields: ["title", "conditions"], revision: "pinned" },
  };
  expect(() => assertComparable(a, b)).not.toThrow();
  b.result.contract = {
    documents: 443,
    model: { fields: ["conditions", "title"], revision: "pinned" },
  };
  expect(() => assertComparable(a, b)).toThrow("comparison withheld");
});
it("validates explicit configuration without relaxing normal defaults", () => {
  const p = { ...search, request: { ...search.request, rerank_depth: 20 } };
  expect(validateRetrieval(p, caseId, defaults)).toEqual(p);
  expect(() =>
    validateRetrieval(p, caseId, { ...defaults, filter: "none" }),
  ).toThrow("configuration");
});
it("sends IDs and the explicit semantic choice only", async () => {
  const fetcher = vi
    .fn()
    .mockResolvedValue(new Response(JSON.stringify(screening)));
  vi.stubGlobal("fetch", fetcher);
  await workbench.screen(caseId, trialId, false, new AbortController().signal);
  expect(JSON.parse(fetcher.mock.calls[0][1].body)).toEqual({
    case_id: caseId,
    trial_id: trialId,
    semantic: false,
  });
});
it("rejects a returned saved operation with the wrong identity", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(new Response(JSON.stringify(fixtureExperiment))),
  );
  await expect(
    workbench.operation(hash, new AbortController().signal),
  ).rejects.toThrow("identity");
});
