import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const storeState = vi.hoisted(() => ({
  apiKey: "backend-key",
  token: "session-token",
}));

const diagnostics = {
  schema_version: 1,
  generated_at: "2026-07-14T09:30:00+00:00",
  app: { name: "FlintTrade", version: "v0.6.0-beta.1" },
  runtime: { os: "Darwin", os_release: "25.5.0", architecture: "arm64", python: "3.12.10" },
  errors: { available: true, total: 0, sampled: 0, groups: [] },
};

vi.mock("@/stores/connectionStore", () => ({
  useConnectionStore: { getState: () => ({ apiKey: storeState.apiKey }) },
}));

vi.mock("@/stores/authStore", () => ({
  useAuthStore: { getState: () => ({ token: storeState.token }) },
}));

import { getSupportDiagnostics } from "../ftApi.support";

describe("ftApi.support", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({
      status: "success",
      data: diagnostics,
    }), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    })));
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("loads diagnostics through the authenticated bare-v1 support route", async () => {
    await expect(getSupportDiagnostics()).resolves.toEqual(diagnostics);

    expect(fetch).toHaveBeenCalledWith("/ft-api/v1/support/diagnostics", {
      headers: {
        "X-API-Key": "backend-key",
        Authorization: "Bearer session-token",
      },
    });
  });

  it("rejects malformed successful diagnostics instead of returning a crash-shaped payload", async () => {
    vi.mocked(fetch).mockResolvedValueOnce(new Response(JSON.stringify({
      status: "success",
      data: { schema_version: 1 },
    }), { status: 200, headers: { "Content-Type": "application/json" } }));

    await expect(getSupportDiagnostics()).rejects.toThrow("Invalid support diagnostics response");
  });

  it("does not call the authenticated endpoint for a frontend-only Explore session", async () => {
    storeState.token = "demo-user";

    await expect(getSupportDiagnostics()).rejects.toThrow("Diagnostics are unavailable in Explore demo");
    expect(fetch).not.toHaveBeenCalled();

    storeState.token = "session-token";
  });
});
