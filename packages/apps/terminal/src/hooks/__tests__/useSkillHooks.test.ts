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
import { useAuthStore } from "@/stores/authStore";
import { useModeStore } from "@/stores/modeStore";
import { useBrokerStore } from "@/stores/brokerStore";
import { useFeatureGate } from "../useFeatureGate";
import { useCommandRegistry } from "@/components/CommandPalette/useCommandRegistry";
import { widgetCatalog } from "@/layout/widgetFactory";
import { assertNativeWriteTargetReadyOrThrow, pickNativeWriteTarget, NATIVE_TARGET_NOT_READY_MESSAGE } from "@/services/brokerTargets";
import type { Domain } from "@/types/skill";

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

// Exercise discovery alongside the real frontend write-target refusal, not a
// mocked readiness result. Presentation compatibility cannot mint authority.
function useDiscovery(domain?: Domain) {
  return {
    level: useSkillLevel(domain),
    gate: useFeatureGate("widget:orderpad", domain),
    commands: useCommandRegistry().commands.filter(command => command.category === "widget").map(command => command.id),
  };
}
function expectDiscoveryOnly(value: ReturnType<typeof useDiscovery>) {
  expect(value.level).toBe("advanced");
  expect(value.gate).toBe("visible");
  expect(value.commands).toEqual(widgetCatalog.map(widget => `widget:${widget.id}`));
  expect(value.commands).toContain("widget:orderpad");
  expect(useAuthStore.getState().status).toBe("logged-out");
  expect(useAuthStore.getState().token).toBeNull();
  expect(useModeStore.getState().mode).toBe("live");
  expect(useBrokerStore.getState().activeAccountId).toBe("native:upstox:READ_ONLY");
  expect(useBrokerStore.getState().accounts[0].read_only).toBe(true);
  expect(pickNativeWriteTarget("live")).toBeUndefined();
  expect(() => assertNativeWriteTargetReadyOrThrow("live")).toThrow(NATIVE_TARGET_NOT_READY_MESSAGE);
}

describe("useSkillLevel", () => {
  beforeEach(() => {
    useAuthStore.setState({ status: "logged-out", token: null });
    useModeStore.setState({ mode: "live" });
    useBrokerStore.setState({ activeAccountId: "native:upstox:READ_ONLY", accounts: [{
      account_id: "READ_ONLY", broker: "upstox", source: "native", status: "connected",
      read_only: true, label: "Synthetic read-only", is_primary: true, connected_at: null, error_message: null,
    }] });
  });

  it("keeps default global discovery open without granting execution authority", () => {
    const { result } = renderHook(() => useDiscovery());
    expect(useSkillStore.getState().globalLevel).toBe("beginner");
    expectDiscoveryOnly(result.current);
  });

  it("keeps domain discovery open without an override or execution authority", () => {
    const { result } = renderHook(() => useDiscovery("trade"));
    expectDiscoveryOnly(result.current);
  });

  it("keeps a domain override presentation-only without execution authority", () => {
    useSkillStore.getState().setRouteOverride("trade", "advanced");
    const { result } = renderHook(() => useDiscovery("trade"));
    expectDiscoveryOnly(result.current);
  });

  it("keeps discovery and authority unchanged after a global level change", () => {
    const { result, rerender } = renderHook(() => useDiscovery());
    expectDiscoveryOnly(result.current);
    act(() => { useSkillStore.getState().setGlobalLevel("intermediate"); });
    rerender();
    expect(useSkillStore.getState().globalLevel).toBe("intermediate");
    expectDiscoveryOnly(result.current);
  });

  it("keeps discovery and authority unchanged when a domain override is cleared", () => {
    useSkillStore.getState().setGlobalLevel("intermediate");
    useSkillStore.getState().setRouteOverride("lab", "advanced");
    const { result, rerender } = renderHook(() => useDiscovery("lab"));
    expectDiscoveryOnly(result.current);
    act(() => { useSkillStore.getState().clearRouteOverride("lab"); });
    rerender();
    expectDiscoveryOnly(result.current);
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
