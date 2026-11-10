import { describe, it, expect, beforeEach, vi } from "vitest";
import { INITIAL_MODE, useModeStore } from "../modeStore";
import type { AppMode } from "../modeStore";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function sessionJwt(mode?: string): string {
  const payload = btoa(JSON.stringify(mode === undefined ? { typ: "session" } : { mode, typ: "session" }))
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/g, "");
  return `header.${payload}.sig`;
}

function seedModeCache(mode: AppMode) {
  localStorage.setItem(
    "flinttrade:mode",
    JSON.stringify({ state: { mode }, version: 2 }),
  );
}

function seedSession(token: string) {
  sessionStorage.setItem(
    "flinttrade:auth-session",
    JSON.stringify({ token, username: "operator", expiresAt: "" }),
  );
}

function resetStore() {
  localStorage.removeItem("flinttrade:mode");
  sessionStorage.removeItem("flinttrade:mode");
  sessionStorage.removeItem("flinttrade:auth-session");
  useModeStore.setState({ mode: INITIAL_MODE });
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
    it("mode defaults to Practice when localStorage is empty", () => {
      expect(INITIAL_MODE).toBe("practice");
      expect(useModeStore.getState().mode).toBe("practice");
    });

    it("a new session with no stored Mode opens in Practice", async () => {
      localStorage.removeItem("flinttrade:mode");
      sessionStorage.removeItem("flinttrade:mode");
      vi.resetModules();
      const fresh = await import("../modeStore");
      await fresh.useModeStore.persist.rehydrate();
      expect(fresh.INITIAL_MODE).toBe("practice");
      expect(fresh.useModeStore.getState().mode).toBe("practice");
      expect(fresh.useModeStore.getState().mode).not.toBe("explore");
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

  describe("session claim beats the mode cache", () => {
    async function bootFreshStore() {
      vi.resetModules();
      return import("../modeStore");
    }

    it("keeps Practice after a reload when the cache says live", async () => {
      seedModeCache("live");
      seedSession(sessionJwt("practice"));
      const fresh = await bootFreshStore();
      expect(fresh.useModeStore.getState().mode).toBe("practice");
      await fresh.useModeStore.persist.rehydrate();
      expect(fresh.useModeStore.getState().mode).toBe("practice");
      expect(JSON.parse(localStorage.getItem("flinttrade:mode") ?? "{}").state.mode).toBe("practice");
    });

    it("reads a Live claim before paint when the cache says practice", async () => {
      seedModeCache("practice");
      seedSession(sessionJwt("live"));
      const fresh = await bootFreshStore();
      expect(fresh.useModeStore.getState().mode).toBe("live");
      await fresh.useModeStore.persist.rehydrate();
      expect(fresh.useModeStore.getState().mode).toBe("live");
    });

    it("shows unavailable for a missing claim instead of the live cache", async () => {
      seedModeCache("live");
      seedSession(sessionJwt());
      const fresh = await bootFreshStore();
      expect(fresh.useModeStore.getState().mode).toBe("unavailable");
    });

    it("shows unavailable for a claim that is not a mode", async () => {
      seedModeCache("live");
      seedSession(sessionJwt("Connected (read)"));
      const fresh = await bootFreshStore();
      expect(fresh.useModeStore.getState().mode).toBe("unavailable");
      expect(fresh.useModeStore.getState().mode).not.toBe("live");
    });
  });
});
