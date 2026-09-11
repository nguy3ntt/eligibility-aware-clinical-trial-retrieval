import { afterEach, describe, expect, it, vi } from "vitest";
import { api, request } from "./client";
import { profileSchema, searchSchema } from "./contracts";
import { caseId, caseItem, profile, search } from "../test/fixtures";

const signal = () => new AbortController().signal;
const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status });
afterEach(() => vi.unstubAllGlobals());
describe("local API contract", () => {
  it("rejects unreadable JSON as a contract failure", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("not json")));
    await expect(api.profile(caseId, signal())).rejects.toMatchObject({
      code: "contract",
    });
  });
  it("rejects contradictory screening summaries", async () => {
    const packet = structuredClone(search);
    packet.result.results[0].screening.status = "potential_match";
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(json(packet)));
    await expect(api.search(caseId, 3, signal())).rejects.toThrow(
      "does not match",
    );
  });
  it("sends only curated ID and fixed defaults, with no credentials", async () => {
    const fetcher = vi.fn().mockResolvedValue(json(search));
    vi.stubGlobal("fetch", fetcher);
    expect(await api.search(caseId, 3, signal())).toEqual(search);
    const [url, options] = fetcher.mock.calls[0];
    expect(url).toBe("/v1/search");
    expect(options.credentials).toBe("omit");
    expect(options.cache).toBe("no-store");
    expect(JSON.parse(options.body)).toEqual(search.request);
  });
  it.each([403, 404, 409, 422, 429, 503, 500])(
    "does not reflect a failing %i response",
    async (status) => {
      vi.stubGlobal(
        "fetch",
        vi.fn().mockResolvedValue(json({ secret: "DO_NOT_REFLECT" }, status)),
      );
      await expect(api.profile(caseId, signal())).rejects.toThrow();
      await api
        .profile(caseId, signal())
        .catch((error) =>
          expect(error.message).not.toContain("DO_NOT_REFLECT"),
        );
    },
  );
  it("rejects malformed successful packets without reflecting their contents", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(json({ secret: "DO_NOT_REFLECT" })),
    );
    await expect(api.profile(caseId, signal())).rejects.toThrow(
      "supported evidence contract",
    );
  });
  it("rejects a profile returned for another case", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue(
          json({ ...profile, case: { ...profile.case, case_id: "wrong" } }),
        ),
    );
    await expect(api.profile(caseId, signal())).rejects.toThrow(
      "does not match",
    );
  });
  it("rejects changed retrieval defaults and promoted advisories", () => {
    expect(
      searchSchema.safeParse({
        ...search,
        result: { ...search.result, method: "hybrid" },
      }).success,
    ).toBe(false);
    expect(
      searchSchema.safeParse({
        ...search,
        result: { ...search.result, semantic_promotion: true },
      }).success,
    ).toBe(false);
  });
  it("rejects nonfinite relevance scores", () => {
    const packet = structuredClone(search);
    packet.result.results[0].relevance.ranking.score = Infinity;
    expect(searchSchema.safeParse(packet).success).toBe(false);
  });
  it("fetches the entire catalog including the 51st case", async () => {
    const first = Array.from({ length: 50 }, (_, i) => ({
      ...caseItem,
      case_id: `case-${i}`,
    }));
    const fetcher = vi
      .fn()
      .mockResolvedValueOnce(
        json({ total: 51, limit: 50, offset: 0, items: first }),
      )
      .mockResolvedValueOnce(
        json({ total: 51, limit: 50, offset: 50, items: [caseItem] }),
      );
    vi.stubGlobal("fetch", fetcher);
    expect(await api.cases(signal())).toHaveLength(51);
    expect(fetcher.mock.calls[1][0]).toContain("offset=50");
  });
  it("rejects incomplete catalogs rather than silently losing cases", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue(
          json({ total: 2, limit: 50, offset: 0, items: [caseItem] }),
        ),
    );
    await expect(api.cases(signal())).rejects.toThrow("incomplete");
  });
  it("preserves cancellation instead of turning it into a displayed service failure", async () => {
    const controller = new AbortController();
    controller.abort();
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("network")));
    await expect(
      request("cases/x", profileSchema, controller.signal),
    ).rejects.toMatchObject({ name: "AbortError" });
  });
});
