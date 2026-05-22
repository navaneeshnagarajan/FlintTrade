/**
 * Tests for Zustand-based skill/behavior hooks:
 *   - useSkillLevel
 *   - useHelpPrefs
 *   - useTrackBehavior
 *
 * Strategy: Use the real skillStore (reset between tests) and verify
 * hooks return correct state and respond to state changes.
 */

import { describe, it, expect, beforeEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useSkillStore } from "@/stores/skillStore";

// ---------------------------------------------------------------------------
// Import hooks
// ---------------------------------------------------------------------------

import { useSkillLevel } from "../useSkillLevel";
import { useHelpPrefs } from "../useHelpPrefs";
import { useTrackBehavior } from "../useTrackBehavior";

// ---------------------------------------------------------------------------
// Reset store between tests
// ---------------------------------------------------------------------------

beforeEach(() => {
  // Reset to defaults
  useSkillStore.getState().resetToDefaults();
});

// ---------------------------------------------------------------------------
// useSkillLevel
// ---------------------------------------------------------------------------

describe("useSkillLevel", () => {
  it("returns global level when no domain is specified", () => {
    const { result } = renderHook(() => useSkillLevel());
    expect(result.current).toBe("beginner"); // default
  });

  it("returns global level for a domain without override", () => {
    const { result } = renderHook(() => useSkillLevel("trade"));
    expect(result.current).toBe("beginner");
  });

  it("returns domain override when one is set", () => {
    useSkillStore.getState().setRouteOverride("trade", "advanced");

    const { result } = renderHook(() => useSkillLevel("trade"));
    expect(result.current).toBe("advanced");
  });

  it("reflects global level changes", () => {
    const { result } = renderHook(() => useSkillLevel());

    act(() => {
      useSkillStore.getState().setGlobalLevel("intermediate");
    });

    expect(result.current).toBe("intermediate");
  });

  it("falls back to global when domain override is cleared", () => {
    useSkillStore.getState().setGlobalLevel("intermediate");
    useSkillStore.getState().setRouteOverride("lab", "advanced");

    const { result, rerender } = renderHook(() => useSkillLevel("lab"));
    expect(result.current).toBe("advanced");

    act(() => {
      useSkillStore.getState().clearRouteOverride("lab");
    });
    rerender();

    expect(result.current).toBe("intermediate");
  });
});

// ---------------------------------------------------------------------------
// useHelpPrefs
// ---------------------------------------------------------------------------

describe("useHelpPrefs", () => {
  it("returns default help preferences", () => {
    const { result } = renderHook(() => useHelpPrefs());

    expect(result.current.inlineHints).toBe(true);
    expect(result.current.spotlightTours).toBe(false);
    expect(result.current.aiTutor).toBe(true);
  });

  it("reflects changes when a pref is updated", () => {
    const { result } = renderHook(() => useHelpPrefs());

    act(() => {
      useSkillStore.getState().setHelpPref("inlineHints", false);
    });

    expect(result.current.inlineHints).toBe(false);
    expect(result.current.spotlightTours).toBe(false); // unchanged
  });

  it("reflects changes after reset to defaults", () => {
    useSkillStore.getState().setHelpPref("aiTutor", false);
    useSkillStore.getState().setHelpPref("spotlightTours", false);

    const { result } = renderHook(() => useHelpPrefs());
    expect(result.current.aiTutor).toBe(false);

    act(() => {
      useSkillStore.getState().resetToDefaults();
    });

    expect(result.current.aiTutor).toBe(true);
    expect(result.current.spotlightTours).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// useTrackBehavior
// ---------------------------------------------------------------------------

describe("useTrackBehavior", () => {
  it("returns a function", () => {
    const { result } = renderHook(() => useTrackBehavior());
    expect(typeof result.current).toBe("function");
  });

  it("increments a known metric when called", () => {
    const { result } = renderHook(() => useTrackBehavior());

    act(() => {
      result.current("trade", "ordersPlaced");
    });

    expect(useSkillStore.getState().metrics.trade.ordersPlaced).toBe(1);
  });

  it("increments multiple times", () => {
    const { result } = renderHook(() => useTrackBehavior());

    act(() => {
      result.current("learn", "lessonsCompleted");
      result.current("learn", "lessonsCompleted");
      result.current("learn", "lessonsCompleted");
    });

    expect(useSkillStore.getState().metrics.learn.lessonsCompleted).toBe(3);
  });

  it("silently ignores unknown action names", () => {
    const { result } = renderHook(() => useTrackBehavior());

    // Should not throw
    act(() => {
      result.current("trade", "unknownAction");
    });

    // Metrics should remain unchanged
    expect(useSkillStore.getState().metrics.trade.ordersPlaced).toBe(0);
  });
});
