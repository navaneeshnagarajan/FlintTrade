import { afterEach, describe, expect, it, vi } from "vitest";

afterEach(() => {
  vi.doUnmock("@sentry/react");
  vi.resetModules();
  vi.restoreAllMocks();
});

describe("optional GlitchTip loading", () => {
  it("does not load the SDK or send requests without a DSN", async () => {
    const loaded = vi.fn();
    vi.doMock("@sentry/react", () => {
      loaded();
      throw new Error("SDK must not load");
    });
    const fetch = vi.spyOn(globalThis, "fetch").mockRejectedValue(new Error("network forbidden"));
    const { initialiseGlitchtip } = await import("../glitchtip");
    await initialiseGlitchtip(undefined, "production");
    await initialiseGlitchtip("", "development");
    expect(loaded).not.toHaveBeenCalled();
    expect(fetch).not.toHaveBeenCalled();
  });

  it("does not interrupt the app when the SDK import fails", async () => {
    vi.doMock("@sentry/react", () => { throw new Error("synthetic import failure"); });
    const { initialiseGlitchtip } = await import("../glitchtip");
    await expect(initialiseGlitchtip("https://synthetic@example.invalid/1", "production"))
      .resolves.toBeUndefined();
  });
});
