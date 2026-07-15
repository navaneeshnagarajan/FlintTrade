import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/stores/authStore", () => ({
  useAuthStore: { getState: () => ({ token: "session-token" }) },
}));

vi.mock("@/stores/connectionStore", () => ({
  useConnectionStore: { getState: () => ({ apiKey: "backend-key" }) },
}));

import {
  dittoKillAll,
  getDittoMirrorStatus,
  normaliseMirrorMode,
} from "../ftApi.ditto";

function response(data: unknown, status = 200): Response {
  return new Response(JSON.stringify({ status: status === 207 ? "partial" : "success", data }), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("ftApi.ditto", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("normalises runtime allocation modes to the two truthful UI modes", () => {
    expect(normaliseMirrorMode("EQUAL")).toBe("equal");
    expect(normaliseMirrorMode("fixed")).toBe("equal");
    expect(normaliseMirrorMode("WEIGHTED")).toBe("weighted");
    expect(normaliseMirrorMode("proportional")).toBe("weighted");
    expect(() => normaliseMirrorMode("capital-aware")).toThrow("unsupported allocation mode");
  });

  it("normalises the backend mirror status before exposing it", async () => {
    vi.mocked(fetch).mockResolvedValue(response({
      active: true,
      source_account: "source",
      target_accounts: ["target"],
      mode: "WEIGHTED",
      mirrored_positions: 2,
      last_sync: null,
      errors: [],
    }));

    await expect(getDittoMirrorStatus()).resolves.toMatchObject({ mode: "weighted" });
  });

  it("rejects an HTTP 207 partial kill-all result as an operator-visible failure", async () => {
    vi.mocked(fetch).mockResolvedValue(response({
      complete: false,
      cleanup_complete: true,
      message: "One or more managed accounts could not be fully flattened",
      accounts_affected: 2,
      emergency_actions: {},
    }, 207));

    await expect(dittoKillAll()).rejects.toThrow(
      "One or more managed accounts could not be fully flattened",
    );
  });
});
