/**
 * Tests for useSkillContent hook.
 *
 * Strategy: use the real skillStore (reset between tests) and verify
 * the hook returns the correct content for each skill level.
 */

import { describe, it, expect, beforeEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useSkillStore } from "@/stores/skillStore";
import { useSkillContent } from "../useSkillContent";
import { widgetCatalog, RETIRED_WIDGET_IDS } from "@/layout/widgetFactory";

// ---------------------------------------------------------------------------
// Reset store between tests
// ---------------------------------------------------------------------------

beforeEach(() => {
  useSkillStore.getState().resetToDefaults();
});

// ---------------------------------------------------------------------------
// Beginner
// ---------------------------------------------------------------------------

describe("useSkillContent — beginner", () => {
  it("returns core widgets only", () => {
    const { result } = renderHook(() => useSkillContent());
    const { availableWidgets } = result.current;

    // Core widgets must be present
    expect(availableWidgets).toContain("chart");
    expect(availableWidgets).toContain("watchlist");
    expect(availableWidgets).toContain("orderpad");
    expect(availableWidgets).toContain("positions");
    expect(availableWidgets).toContain("indexstrip");

    // Analysis widgets must NOT be present at beginner level
    expect(availableWidgets).not.toContain("optionchain");
    expect(availableWidgets).not.toContain("straddle");
    expect(availableWidgets).not.toContain("volsurface");
    expect(availableWidgets).not.toContain("scalper");
  });

  it("returns settings-only tools", () => {
    const { result } = renderHook(() => useSkillContent());
    expect(result.current.availableTools).toContain("settings");
    expect(result.current.availableTools).not.toContain("market-intelligence");
    expect(result.current.availableTools).not.toContain("trade-journal");
  });

  it("returns showAdvanced false", () => {
    const { result } = renderHook(() => useSkillContent());
    expect(result.current.showAdvanced).toBe(false);
  });

  it("returns simple tooltip level", () => {
    const { result } = renderHook(() => useSkillContent());
    expect(result.current.tooltipLevel).toBe("simple");
  });

  it("returns beginner-core default preset", () => {
    const { result } = renderHook(() => useSkillContent());
    expect(result.current.defaultPreset).toBe("beginner-core");
  });
});

// ---------------------------------------------------------------------------
// Intermediate
// ---------------------------------------------------------------------------

describe("useSkillContent — intermediate", () => {
  beforeEach(() => {
    useSkillStore.getState().setGlobalLevel("intermediate");
  });

  it("includes core widgets", () => {
    const { result } = renderHook(() => useSkillContent());
    expect(result.current.availableWidgets).toContain("chart");
    expect(result.current.availableWidgets).toContain("orderpad");
  });

  it("includes analysis widgets", () => {
    const { result } = renderHook(() => useSkillContent());
    expect(result.current.availableWidgets).toContain("optionchain");
    expect(result.current.availableWidgets).toContain("straddle");
    // depth merged into orderladder.
    expect(result.current.availableWidgets).toContain("orderladder");
    expect(result.current.availableWidgets).toContain("greeks");
    expect(result.current.availableWidgets).toContain("oichart");
    expect(result.current.availableWidgets).toContain("marketoverview");
    // gex merged into gammadensity.
    expect(result.current.availableWidgets).toContain("gammadensity");
  });

  it("does not include advanced-only widgets", () => {
    const { result } = renderHook(() => useSkillContent());
    expect(result.current.availableWidgets).not.toContain("volsurface");
    expect(result.current.availableWidgets).not.toContain("scalper");
    expect(result.current.availableWidgets).not.toContain("orderflow");
  });

  it("includes trade-journal tool", () => {
    const { result } = renderHook(() => useSkillContent());
    expect(result.current.availableTools).toContain("trade-journal");
    expect(result.current.availableTools).toContain("settings");
    expect(result.current.availableTools).not.toContain("market-intelligence");
  });

  it("returns detailed tooltip level", () => {
    const { result } = renderHook(() => useSkillContent());
    expect(result.current.tooltipLevel).toBe("detailed");
  });

  it("returns market-watch default preset", () => {
    const { result } = renderHook(() => useSkillContent());
    expect(result.current.defaultPreset).toBe("market-watch");
  });

  it("returns showAdvanced false", () => {
    const { result } = renderHook(() => useSkillContent());
    expect(result.current.showAdvanced).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// Advanced
// ---------------------------------------------------------------------------

describe("useSkillContent — advanced", () => {
  beforeEach(() => {
    useSkillStore.getState().setGlobalLevel("advanced");
  });

  it("includes all widget tiers", () => {
    const { result } = renderHook(() => useSkillContent());
    const { availableWidgets } = result.current;

    // Beginner tier
    expect(availableWidgets).toContain("chart");
    expect(availableWidgets).toContain("orderpad");

    // Intermediate tier
    expect(availableWidgets).toContain("optionchain");
    expect(availableWidgets).toContain("marketoverview");

    // Advanced-only
    expect(availableWidgets).toContain("volsurface");
    expect(availableWidgets).toContain("scalper");
    expect(availableWidgets).toContain("orderflow");
    // depthheatmap merged into domheatmap (its gamma-scale look).
    expect(availableWidgets).toContain("domheatmap");
    expect(availableWidgets).not.toContain("depthheatmap");
    expect(availableWidgets).toContain("conditionscanner");
    // Order-flow widgets. `footprint` merged into `orderflow` (its
    // "footprint+delta" view mode), so the canonical id is what the picker can reach
    // them (they were registered + functional but in no skill tier).
    expect(availableWidgets).toContain("orderflow");
    // The retired id must NOT come back into the picker.
    expect(availableWidgets).not.toContain("footprint");
    expect(availableWidgets).toContain("domheatmap");
  });

  it("includes all tools", () => {
    const { result } = renderHook(() => useSkillContent());
    expect(result.current.availableTools).toContain("market-intelligence");
    expect(result.current.availableTools).toContain("trade-journal");
    expect(result.current.availableTools).toContain("settings");
  });

  it("returns showAdvanced true", () => {
    const { result } = renderHook(() => useSkillContent());
    expect(result.current.showAdvanced).toBe(true);
  });

  it("returns expert tooltip level", () => {
    const { result } = renderHook(() => useSkillContent());
    expect(result.current.tooltipLevel).toBe("expert");
  });

  it("returns scalper-zone default preset", () => {
    const { result } = renderHook(() => useSkillContent());
    expect(result.current.defaultPreset).toBe("scalper-zone");
  });
});

// ---------------------------------------------------------------------------
// Reactivity — hook updates when skill level changes
// ---------------------------------------------------------------------------

describe("useSkillContent — reactivity", () => {
  it("updates when global level changes", () => {
    const { result } = renderHook(() => useSkillContent());

    // Start as beginner
    expect(result.current.tooltipLevel).toBe("simple");
    expect(result.current.availableWidgets).not.toContain("optionchain");

    act(() => {
      useSkillStore.getState().setGlobalLevel("advanced");
    });

    expect(result.current.tooltipLevel).toBe("expert");
    expect(result.current.availableWidgets).toContain("optionchain");
    expect(result.current.availableWidgets).toContain("volsurface");
  });

  it("respects domain override for trade", () => {
    // Global is beginner but trade override is advanced
    useSkillStore.getState().setRouteOverride("trade", "advanced");

    const { result } = renderHook(() => useSkillContent());

    expect(result.current.showAdvanced).toBe(true);
    expect(result.current.tooltipLevel).toBe("expert");
    expect(result.current.availableWidgets).toContain("scalper");
  });

  it("falls back to global when override is cleared", () => {
    useSkillStore.getState().setGlobalLevel("intermediate");
    useSkillStore.getState().setRouteOverride("trade", "advanced");

    const { result, rerender } = renderHook(() => useSkillContent());
    expect(result.current.showAdvanced).toBe(true);

    act(() => {
      useSkillStore.getState().clearRouteOverride("trade");
    });
    // Force re-render to pick up routeOverrides change (mirrors the pattern
    // used in the existing useSkillLevel tests for the same reason)
    rerender();

    // Should now use intermediate
    expect(result.current.showAdvanced).toBe(false);
    expect(result.current.tooltipLevel).toBe("detailed");
  });
});

// ---------------------------------------------------------------------------
// Additive invariant — higher levels are supersets of lower levels
// ---------------------------------------------------------------------------

describe("useSkillContent — additive invariant", () => {
  it("intermediate widgets is a superset of beginner widgets", () => {
    useSkillStore.getState().setGlobalLevel("beginner");
    const { result: beginnerResult } = renderHook(() => useSkillContent());
    const beginnerWidgets = new Set(beginnerResult.current.availableWidgets);

    act(() => {
      useSkillStore.getState().setGlobalLevel("intermediate");
    });

    const intermediateWidgets = beginnerResult.current.availableWidgets;
    for (const id of beginnerWidgets) {
      expect(intermediateWidgets).toContain(id);
    }
  });

  it("advanced widgets is a superset of intermediate widgets", () => {
    useSkillStore.getState().setGlobalLevel("intermediate");
    const { result } = renderHook(() => useSkillContent());
    const intermediateWidgets = [...result.current.availableWidgets];

    act(() => {
      useSkillStore.getState().setGlobalLevel("advanced");
    });

    const advancedWidgets = result.current.availableWidgets;
    for (const id of intermediateWidgets) {
      expect(advancedWidgets).toContain(id);
    }
  });

  it("advanced tier covers EVERY catalogued widget (no picker drift)", () => {
    // Regression guard for the bug where ~50 registered widgets were unreachable
    // because ADVANCED_WIDGETS was a hand-maintained list that fell behind the
    // catalog. The advanced picker must expose every widgetCatalog id.
    useSkillStore.getState().setGlobalLevel("advanced");
    const { result } = renderHook(() => useSkillContent());
    const advanced = new Set(result.current.availableWidgets);
    for (const w of widgetCatalog) {
      expect(advanced.has(w.id)).toBe(true);
    }
  });

  it("advanced tools is a superset of intermediate tools", () => {
    useSkillStore.getState().setGlobalLevel("intermediate");
    const { result } = renderHook(() => useSkillContent());
    const intermediateTools = [...result.current.availableTools];

    act(() => {
      useSkillStore.getState().setGlobalLevel("advanced");
    });

    const advancedTools = result.current.availableTools;
    for (const id of intermediateTools) {
      expect(advancedTools).toContain(id);
    }
  });
});

describe("useSkillContent — merged canonicals stay reachable per tier", () => {
  // The tier lists are by widget id, and a retired id leaves widgetCatalog —
  // which the picker intersects against. So a merge silently removes a surface
  // from a tier unless the canonical is added in the same change.
  it("keeps the intermediate tier's analysis surfaces after the merges", () => {
    useSkillStore.getState().setGlobalLevel("intermediate");
    const { result } = renderHook(() => useSkillContent());
    const widgets = result.current.availableWidgets;

    // depth -> orderladder, gex -> gammadensity.
    expect(widgets).toContain("orderladder");
    expect(widgets).toContain("gammadensity");
    expect(widgets).not.toContain("depth");
    expect(widgets).not.toContain("gex");
  });

  it("lists no retired id in any tier", () => {
    for (const level of ["beginner", "intermediate", "advanced"] as const) {
      useSkillStore.getState().setGlobalLevel(level);
      const { result } = renderHook(() => useSkillContent());
      for (const id of Object.keys(RETIRED_WIDGET_IDS)) {
        expect(
          result.current.availableWidgets,
          `${level} tier lists retired id ${id}`,
        ).not.toContain(id);
      }
    }
  });
});
