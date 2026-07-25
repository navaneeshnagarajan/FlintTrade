import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/stores/authStore", () => ({
  useAuthStore: { getState: () => ({ token: "session-token" }) },
}));

// Mutable so the write-target hydration state can be driven per test.
const mockConnection = vi.hoisted(() => ({
  apiKey: "backend-key",
  openAlgoHydrated: true,
}));
const mockMode = vi.hoisted(() => ({ current: "practice" }));

vi.mock("@/stores/connectionStore", () => ({
  useConnectionStore: { getState: () => mockConnection },
}));

vi.mock("@/stores/modeStore", () => ({
  useModeStore: { getState: () => ({ mode: mockMode.current }) },
}));

import {
  dittoKillAll,
  getDittoMirrorStatus,
  normaliseMirrorMode,
  startDittoMirror,
  stopDittoMirror,
  setDittoAccountEnabled,
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

// ---------------------------------------------------------------------------
// Arming the mirror is a live-order decision. It previously reached the
// backend with no native write-target assert at all, so a start issued while
// the OpenAlgo config was still hydrating could arm the mirror against a
// different account than the operator was looking at.
// ---------------------------------------------------------------------------

describe("ditto mirror arming fails closed on an unready write target", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
    mockMode.current = "practice";
    mockConnection.openAlgoHydrated = true;
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("refuses to start the mirror in live mode before the config hydrates", async () => {
    mockMode.current = "live";
    mockConnection.openAlgoHydrated = false;

    await expect(startDittoMirror("acc-1", ["acc-2"], "equal")).rejects.toThrow(
      /still loading/i,
    );
    expect(fetch).not.toHaveBeenCalled();
  });

  it("refuses to enable a mirror account in live mode before the config hydrates", async () => {
    mockMode.current = "live";
    mockConnection.openAlgoHydrated = false;

    await expect(setDittoAccountEnabled("acc-2", true)).rejects.toThrow(/still loading/i);
    expect(fetch).not.toHaveBeenCalled();
  });

  it("still allows disabling an account while unhydrated — narrowing risk is never gated", async () => {
    mockMode.current = "live";
    mockConnection.openAlgoHydrated = false;
    vi.mocked(fetch).mockResolvedValue(response({ account: { id: "acc-2" } }));

    await expect(setDittoAccountEnabled("acc-2", false)).resolves.toBeTruthy();
    expect(fetch).toHaveBeenCalled();
  });

  it("still allows stopping the mirror while unhydrated — disarming is never gated", async () => {
    mockMode.current = "live";
    mockConnection.openAlgoHydrated = false;
    vi.mocked(fetch).mockResolvedValue(response({ active: false, stopped_at: "now" }));

    await expect(stopDittoMirror()).resolves.toBeTruthy();
    expect(fetch).toHaveBeenCalled();
  });

  it("starts the mirror once the write target is ready", async () => {
    mockMode.current = "live";
    mockConnection.openAlgoHydrated = true;
    vi.mocked(fetch).mockResolvedValue(
      response({ active: true, source_account: "acc-1", target_accounts: ["acc-2"], mode: "equal" }),
    );

    await expect(startDittoMirror("acc-1", ["acc-2"], "equal")).resolves.toMatchObject({
      mode: "equal",
    });
    expect(fetch).toHaveBeenCalled();
  });
});
