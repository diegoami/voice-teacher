import { describe, it, expect, vi, afterEach } from "vitest";
import {
  api,
  ApiError,
  serverOrigin,
  readGrant,
  readSessions,
  readChoice,
} from "../src/api";
afterEach(() => vi.unstubAllGlobals());
describe("private server connection", () => {
  it("accepts only a clean HTTPS or loopback origin", () => {
    expect(serverOrigin("https://lessons.example.org")).toBe(
      "https://lessons.example.org",
    );
    expect(serverOrigin("http://localhost:8000/")).toBe(
      "http://localhost:8000",
    );
    for (const v of [
      "javascript:alert(1)",
      "http://192.168.0.2",
      "https://user:secret@example.org",
      "https://example.org/path",
      "https://example.org/?token=secret",
    ])
      expect(() => serverOrigin(v)).toThrow();
  });
  it("uses same-origin bearer authorization with no cookies or cache and no query token", async () => {
    const fetch = vi
      .fn()
      .mockResolvedValue(new Response(JSON.stringify({ learner_id: "one" })));
    vi.stubGlobal("fetch", fetch);
    await expect(api("/identity", "synthetic-client-token")).resolves.toEqual({
      learner_id: "one",
    });
    expect(fetch.mock.calls[0][0]).toBe("/api/v1/identity");
    expect(fetch.mock.calls[0][1]).toMatchObject({
      headers: { Authorization: "Bearer synthetic-client-token" },
      cache: "no-store",
      credentials: "omit",
      redirect: "error",
    });
  });
  it("never renders arbitrary server error payloads", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue(new Response("SYNTHETIC_SECRET", { status: 502 })),
    );
    await expect(api("/sources")).rejects.toThrow(ApiError);
    await expect(api("/sources")).rejects.not.toThrow("SYNTHETIC_SECRET");
  });
  it("refuses expired or malformed locally stored grants and choices", () => {
    const storage = { getItem: () => "{broken" } as unknown as Storage;
    expect(readGrant(storage)).toBeNull();
    vi.stubGlobal("localStorage", {
      getItem: () => JSON.stringify({ unexpected: "object" }),
    });
    expect(readSessions("learner")).toEqual([]);
    expect(readChoice("learner").source_id).toBe("");
    expect(
      readGrant({
        getItem: () =>
          JSON.stringify({
            token: "x".repeat(40),
            client_id: "one",
            learner_id: "one",
            expires_at: 0,
          }),
      } as unknown as Storage),
    ).toBeNull();
  });
});
