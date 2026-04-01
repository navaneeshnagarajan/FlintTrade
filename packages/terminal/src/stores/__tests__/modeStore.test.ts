import { describe, it, expect, beforeEach } from "vitest";
import { useModeStore } from "../modeStore";
import type { AppMode } from "../modeStore";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function resetStore() {
  useModeStore.setState({ mode: "demo" });
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("modeStore", () => {
  beforeEach(() => {
    resetStore();
  });

  // --- Default state --------------------------------------------------------

  describe("default state", () => {
    it("mode defaults to demo", () => {
      expect(useModeStore.getState().mode).toBe("demo");
    });
  });

  // --- setMode --------------------------------------------------------------

  describe("setMode", () => {
    it("changes mode to sandbox", () => {
      useModeStore.getState().setMode("sandbox");
      expect(useModeStore.getState().mode).toBe("sandbox");
    });

    it("changes mode to live", () => {
      useModeStore.getState().setMode("live");
      expect(useModeStore.getState().mode).toBe("live");
    });

    it("changes mode back to demo from live", () => {
      useModeStore.getState().setMode("live");
      useModeStore.getState().setMode("demo");
      expect(useModeStore.getState().mode).toBe("demo");
    });

    it("accepts all three valid modes without throwing", () => {
      const modes: AppMode[] = ["demo", "sandbox", "live"];
      for (const m of modes) {
        expect(() => useModeStore.getState().setMode(m)).not.toThrow();
      }
    });
  });

  // --- requiresPinForMode ---------------------------------------------------

  describe("requiresPinForMode", () => {
    it("returns true for live mode", () => {
      expect(useModeStore.getState().requiresPinForMode("live")).toBe(true);
    });

    it("returns false for sandbox mode", () => {
      expect(useModeStore.getState().requiresPinForMode("sandbox")).toBe(false);
    });

    it("returns false for demo mode", () => {
      expect(useModeStore.getState().requiresPinForMode("demo")).toBe(false);
    });

    it("is a pure function — result does not depend on current mode", () => {
      useModeStore.getState().setMode("live");
      // Even when current mode is live, checking for demo is still false
      expect(useModeStore.getState().requiresPinForMode("demo")).toBe(false);
      expect(useModeStore.getState().requiresPinForMode("sandbox")).toBe(false);
      expect(useModeStore.getState().requiresPinForMode("live")).toBe(true);
    });
  });
});
