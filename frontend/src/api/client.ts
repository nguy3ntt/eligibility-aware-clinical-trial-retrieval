import { z } from "zod";
import {
  casePageSchema,
  profileSchema,
  readySchema,
  searchSchema,
  trialPageSchema,
  trialSchema,
} from "./contracts";

export class ApiError extends Error {
  constructor(
    public readonly code: string,
    message: string,
  ) {
    super(message);
  }
}
const failures: Record<number, string> = {
  403: "This workspace only accepts local requests.",
  404: "This catalog record is unavailable. Refresh the catalog and try again.",
  409: "Evidence or version validation failed. No result was accepted.",
  422: "The request was rejected. Refresh the workspace and try again.",
  429: "Another operation is running. Wait briefly, then try again.",
  503: "A local database, index or model is unavailable. Start the project services and retry.",
};
export async function request<T>(
  path: string,
  schema: z.ZodType<T>,
  signal: AbortSignal,
  body?: object,
): Promise<T> {
  try {
    const response = await fetch(`/v1/${path}`, {
      signal: AbortSignal.any([signal, AbortSignal.timeout(180000)]),
      method: body ? "POST" : "GET",
      headers: body ? { "Content-Type": "application/json" } : undefined,
      body: body ? JSON.stringify(body) : undefined,
      credentials: "omit",
      cache: "no-store",
      redirect: "error",
    });
    if (!response.ok)
      throw new ApiError(
        String(response.status),
        failures[response.status] ??
          "The local service could not complete this request. Try again.",
      );
    const payload: unknown = await response.json().catch(() => {
      throw new ApiError(
        "contract",
        "The service returned unreadable data. No evidence was displayed.",
      );
    });
    const parsed = schema.safeParse(payload);
    if (!parsed.success)
      throw new ApiError(
        "contract",
        "The response does not match the supported evidence contract. Nothing was displayed.",
      );
    return parsed.data;
  } catch (error) {
    if (signal.aborted)
      throw new DOMException("Request cancelled", "AbortError");
    if (error instanceof ApiError) throw error;
    if (error instanceof DOMException && error.name === "TimeoutError")
      throw new ApiError(
        "timeout",
        "The request timed out. The server may still finish it; retrying can recover the saved result.",
      );
    throw new ApiError(
      "connection",
      "Cannot reach the local API. Check the project services, then retry.",
    );
  }
}
export const api = {
  ready: (signal: AbortSignal) => request("ready", readySchema, signal),
  cases: async (signal: AbortSignal) => {
    const first = await request(
      "cases?limit=50&offset=0",
      casePageSchema,
      signal,
    );
    const items = [...first.items];
    // Fetch every bounded catalog page, including the 51st case; never silently truncate.
    if (first.total > 10000)
      throw new ApiError(
        "catalog",
        "The catalog exceeds this bounded workspace.",
      );
    for (let offset = 50; offset < first.total; offset += 50) {
      const page = await request(
        `cases?limit=50&offset=${offset}`,
        casePageSchema,
        signal,
      );
      if (page.total !== first.total)
        throw new ApiError(
          "catalog",
          "The catalog changed while loading. Retry.",
        );
      items.push(...page.items);
    }
    if (
      items.length !== first.total ||
      new Set(items.map((c) => c.case_id)).size !== items.length
    )
      throw new ApiError(
        "catalog",
        "The catalog is incomplete. Retry before selecting a case.",
      );
    return items.sort((a, b) =>
      a.case_id.localeCompare(b.case_id, undefined, { numeric: true }),
    );
  },
  profile: async (id: string, signal: AbortSignal) => {
    const profile = await request(
      `cases/${encodeURIComponent(id)}`,
      profileSchema,
      signal,
    );
    if (profile.case.case_id !== id)
      throw new ApiError(
        "identity",
        "The returned case does not match your selection.",
      );
    return profile;
  },
  trial: async (id: string, signal: AbortSignal) => {
    const trial = await request(
      `trials/${encodeURIComponent(id)}`,
      trialSchema,
      signal,
    );
    if (trial.evidence.trial_id !== id || trial.criteria.source.trial_id !== id)
      throw new ApiError(
        "identity",
        "The returned trial does not match your selection.",
      );
    return trial;
  },
  trials: (offset: number, signal: AbortSignal) =>
    request(`trials?limit=20&offset=${offset}`, trialPageSchema, signal),
  search: async (id: string, topK: number, signal: AbortSignal) => {
    const result = await request("search", searchSchema, signal, {
      case_id: id,
      method: "dense",
      filter: "age_sex",
      fact_extractor: "legacy",
      rerank: false,
      top_k: topK,
    });
    if (
      result.request.case_id !== id ||
      result.request.top_k !== topK ||
      result.result.results.length > topK ||
      new Set(result.result.results.map((r) => r.trial_id)).size !==
        result.result.results.length ||
      result.result.results.some(
        (r, i) =>
          r.relevance.ranking.rank !== i + 1 ||
          r.screening.status !== r.eligibility_assessment,
      )
    )
      throw new ApiError(
        "identity",
        "The returned search does not match your request.",
      );
    return result;
  },
};
