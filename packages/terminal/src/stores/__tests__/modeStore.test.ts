import { describe, it, expect, beforeEach } from "vitest";
import { useModeStore } from "../modeStore";
import type { AppMode } from "../modeStore";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function resetStore() {
  useModeStore.setState({ mode: "explore" });
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
    it("mode defaults to explore", () => {
      expect(useModeStore.getState().mode).toBe("explore");
    });
  });

  // --- setMode --------------------------------------------------------------

  describe("setMode", () => {
    it("changes mode to practice", () => {
      useModeStore.getState().setMode("practice");
      expect(useModeStore.getState().mode).toBe("practice");
    });

    it("changes mode to live", () => {
      useModeStore.getState().setMode("live");
      expect(useModeStore.getState().mode).toBe("live");
    });

    it("changes mode back to explore from live", () => {
      useModeStore.getState().setMode("live");
      useModeStore.getState().setMode("explore");
      expect(useModeStore.getState().mode).toBe("explore");
    });

    it("accepts all three valid modes without throwing", () => {
      const modes: AppMode[] = ["explore", "practice", "live"];
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

    it("returns false for practice mode", () => {
      expect(useModeStore.getState().requiresPinForMode("practice")).toBe(false);
    });

    it("returns false for explore mode", () => {
      expect(useModeStore.getState().requiresPinForMode("explore")).toBe(false);
    });

    it("is a pure function — result does not depend on current mode", () => {
      useModeStore.getState().setMode("live");
      // Even when current mode is live, checking for other modes is still false
      expect(useModeStore.getState().requiresPinForMode("explore")).toBe(false);
      expect(useModeStore.getState().requiresPinForMode("practice")).toBe(false);
      expect(useModeStore.getState().requiresPinForMode("live")).toBe(true);
    });
  });

  // --- isPractice -----------------------------------------------------------

  describe("isPractice", () => {
    it("returns false when mode is explore", () => {
      useModeStore.setState({ mode: "explore" });
      expect(useModeStore.getState().isPractice()).toBe(false);
    });

    it("returns true when mode is practice", () => {
      useModeStore.setState({ mode: "practice" });
      expect(useModeStore.getState().isPractice()).toBe(true);
    });

    it("returns false when mode is live", () => {
      useModeStore.setState({ mode: "live" });
      expect(useModeStore.getState().isPractice()).toBe(false);
    });

    it("updates reactively when mode changes", () => {
      useModeStore.getState().setMode("practice");
      expect(useModeStore.getState().isPractice()).toBe(true);
      useModeStore.getState().setMode("live");
      expect(useModeStore.getState().isPractice()).toBe(false);
    });
  });
});
