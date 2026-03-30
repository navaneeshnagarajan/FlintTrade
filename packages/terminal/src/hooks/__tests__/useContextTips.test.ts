/**
 * useContextTips.test.ts
 *
 * Tests for the useContextTips hook — verifies tip selection by trigger,
 * difficulty filtering by skill level, dismiss persistence, and help-prefs gating.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useContextTips } from "../useContextTips";

// ---------------------------------------------------------------------------
// Mock skillStore
// ---------------------------------------------------------------------------

const mockState = {
  globalLevel: "beginner" as "beginner" | "intermediate" | "advanced",
  helpPrefs: { inlineHints: true, spotlightTours: true, aiTutor: true },
};

vi.mock("@/stores/skillStore", () => ({
  useSkillStore: (selector: (s: typeof mockState) => unknown) => selector(mockState),
}));

// ---------------------------------------------------------------------------
// localStorage mock
// ---------------------------------------------------------------------------

let storage: Record<string, string> = {};

beforeEach(() => {
  storage = {};
  vi.spyOn(Storage.prototype, "getItem").mockImplementation(
    (key: string) => storage[key] ?? null,
  );
  vi.spyOn(Storage.prototype, "setItem").mockImplementation(
    (key: string, value: string) => {
      storage[key] = value;
    },
  );
  // Reset skill level to beginner
  mockState.globalLevel = "beginner";
  mockState.helpPrefs.inlineHints = true;
});

afterEach(() => {
  vi.restoreAllMocks();
});

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("useContextTips", () => {
  it("returns a beginner tip for widget:optionchain trigger", () => {
    const { result } = renderHook(() => useContextTips("widget:optionchain"));
    expect(result.current.tip).not.toBeNull();
    expect(result.current.tip?.trigger).toBe("widget:optionchain");
    expect(result.current.tip?.difficulty).toBe("beginner");
  });

  it("returns null for an unknown trigger", () => {
    const { result } = renderHook(() => useContextTips("widget:nonexistent"));
    expect(result.current.tip).toBeNull();
  });

  it("dismisses a tip and persists to localStorage", () => {
    const { result } = renderHook(() => useContextTips("widget:optionchain"));
    const tipId = result.current.tip?.id;
    expect(tipId).toBeDefined();

    act(() => {
      result.current.dismiss();
    });

    // Tip should change (next tip or null)
    expect(result.current.tip?.id).not.toBe(tipId);

    // localStorage should contain the dismissed ID
    const stored = JSON.parse(storage["flinttrade:dismissed-tips"] ?? "[]") as string[];
    expect(stored).toContain(tipId);
  });

  it("filters by skill level — beginner does not see intermediate tips", () => {
    mockState.globalLevel = "beginner";
    const { result } = renderHook(() => useContextTips("widget:optionchain"));
    // All returned tips should be beginner level
    if (result.current.tip) {
      expect(result.current.tip.difficulty).toBe("beginner");
    }
  });

  it("intermediate users see beginner and intermediate tips", () => {
    mockState.globalLevel = "intermediate";
    const { result } = renderHook(() => useContextTips("widget:optionchain"));
    if (result.current.tip) {
      expect(["beginner", "intermediate"]).toContain(result.current.tip.difficulty);
    }
  });

  it("returns null when inlineHints is disabled", () => {
    mockState.helpPrefs.inlineHints = false;
    const { result } = renderHook(() => useContextTips("widget:optionchain"));
    expect(result.current.tip).toBeNull();
  });

  it("returns a tip for widget:chart trigger", () => {
    const { result } = renderHook(() => useContextTips("widget:chart"));
    expect(result.current.tip).not.toBeNull();
    expect(result.current.tip?.trigger).toBe("widget:chart");
    expect(result.current.tip?.category).toBe("technical");
  });

  it("returns a tip for widget:greeks trigger", () => {
    const { result } = renderHook(() => useContextTips("widget:greeks"));
    expect(result.current.tip).not.toBeNull();
    expect(result.current.tip?.trigger).toBe("widget:greeks");
    expect(result.current.tip?.category).toBe("options");
  });

  it("returns a tip for widget:scalper trigger", () => {
    const { result } = renderHook(() => useContextTips("widget:scalper"));
    expect(result.current.tip).not.toBeNull();
    expect(result.current.tip?.category).toBe("risk");
  });

  it("returns a tip for widget:dashboard trigger", () => {
    const { result } = renderHook(() => useContextTips("widget:dashboard"));
    expect(result.current.tip).not.toBeNull();
    expect(result.current.tip?.category).toBe("risk");
  });
});
