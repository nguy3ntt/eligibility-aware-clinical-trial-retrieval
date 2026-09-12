import { ApiError, request } from "./client";
import { retrievalSchema, trialPageSchema, type Search } from "./contracts";
import {
  fixtureExperimentSchema,
  operationPageSchema,
  operationSchema,
  screeningSchema,
} from "./workbenchContracts";

export type RetrievalOptions = {
  method: "dense" | "sparse" | "hybrid";
  filter: "age_sex" | "none";
  fact_extractor: "legacy" | "profile";
  rerank: boolean;
  rerank_depth: number;
  top_k: number;
};
export const defaults: RetrievalOptions = {
  method: "dense",
  filter: "age_sex",
  fact_extractor: "legacy",
  rerank: false,
  rerank_depth: 20,
  top_k: 3,
};
export function validateRetrieval(
  packet: Search,
  id: string,
  options: RetrievalOptions,
) {
  if (
    packet.request.case_id !== id ||
    Object.entries(options).some(([k, v]) => packet.request[k] !== v) ||
    packet.result.method !== options.method ||
    packet.result.filter !== options.filter ||
    packet.result.fact_extractor !== options.fact_extractor ||
    Boolean(packet.result.reranker) !==
      (options.rerank && packet.result.candidate_count > 0) ||
    packet.result.results.length > options.top_k ||
    new Set(packet.result.results.map((r) => r.trial_id)).size !==
      packet.result.results.length ||
    packet.result.results.some(
      (r, i) =>
        r.relevance.ranking.rank !== i + 1 ||
        r.screening.status !== r.eligibility_assessment,
    )
  )
    throw new ApiError(
      "identity",
      "The returned ranking does not match this configuration.",
    );
  return packet;
}
export const workbench = {
  trialChoices: async (signal: AbortSignal) => {
    const first = await request(
      "trials?limit=50&offset=0",
      trialPageSchema,
      signal,
    );
    if (first.total > 10000)
      throw new ApiError(
        "catalog",
        "Trial catalog exceeds this bounded workspace.",
      );
    const items = [...first.items];
    for (let offset = 50; offset < first.total; offset += 50) {
      const page = await request(
        `trials?limit=50&offset=${offset}`,
        trialPageSchema,
        signal,
      );
      if (page.total !== first.total)
        throw new ApiError("catalog", "The trial catalog changed. Retry.");
      items.push(...page.items);
    }
    if (
      items.length !== first.total ||
      new Set(items.map((t) => t.trial_id)).size !== items.length
    )
      throw new ApiError("catalog", "The trial catalog is incomplete. Retry.");
    return items;
  },
  screen: async (
    case_id: string,
    trial_id: string,
    semantic: boolean,
    signal: AbortSignal,
  ) => {
    const packet = await request("screening", screeningSchema, signal, {
      case_id,
      trial_id,
      semantic,
    });
    if (
      packet.request.case_id !== case_id ||
      packet.request.trial_id !== trial_id ||
      packet.request.semantic !== semantic
    )
      throw new ApiError(
        "identity",
        "Screening belongs to a different request.",
      );
    return packet;
  },
  retrieve: async (
    id: string,
    options: RetrievalOptions,
    signal: AbortSignal,
  ) =>
    validateRetrieval(
      await request("search", retrievalSchema, signal, {
        case_id: id,
        ...options,
      }),
      id,
      options,
    ),
  operations: (offset: number, signal: AbortSignal) =>
    request(
      `experiments?limit=20&offset=${offset}`,
      operationPageSchema,
      signal,
    ),
  operation: async (id: string, signal: AbortSignal) => {
    const packet = await request(
      `experiments/${encodeURIComponent(id)}`,
      operationSchema,
      signal,
    );
    if (packet.operation_id !== id)
      throw new ApiError(
        "identity",
        "Stored operation identity does not match.",
      );
    return packet;
  },
  experiment: (signal: AbortSignal) =>
    request("experiments", fixtureExperimentSchema, signal, {
      configuration: "screening-fixtures-v1",
    }),
};
// PostgreSQL JSONB may reorder object keys on replay. Preserve array order,
// but compare object contents independently of their serialization order.
function canonical(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonical).join(",")}]`;
  if (value !== null && typeof value === "object")
    return `{${Object.entries(value)
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([key, entry]) => `${JSON.stringify(key)}:${canonical(entry)}`)
      .join(",")}}`;
  return JSON.stringify(value) ?? "undefined";
}
export function assertComparable(a: Search, b: Search) {
  if (
    a.request.case_id !== b.request.case_id ||
    a.provenance.catalog_sha256 !== b.provenance.catalog_sha256 ||
    a.provenance.implementation_sha256 !== b.provenance.implementation_sha256 ||
    canonical(a.provenance.runtime_versions) !==
      canonical(b.provenance.runtime_versions) ||
    canonical(a.result.contract) !== canonical(b.result.contract)
  )
    throw new ApiError(
      "comparison",
      "Sources, implementation or runtime changed between runs; comparison withheld.",
    );
}
