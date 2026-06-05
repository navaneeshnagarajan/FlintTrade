import { describe, it, expect } from "vitest";
import { FEATURE_GATES } from "@/lib/featureGates";
import type { SkillLevel } from "@/types/skill";
import type { GateStatus } from "@/hooks/useFeatureGate";

// ---------------------------------------------------------------------------
// Tests for the pure gate resolution logic that useFeatureGate wraps.
//
// useFeatureGate does exactly two things:
//   1. Resolve the effective skill level (via useSkillLevel / useSkillStore)
//   2. Look up FEATURE_GATES[featureId][level]
//
// The hook itself is trivially thin.  These tests exercise both the lookup
// contract (FEATURE_GATES shape) and the edge-case defaults without needing
// a React rendering environment or a running Zustand store.
// ---------------------------------------------------------------------------

/**
 * Mirrors useFeatureGate's resolution step without any React/Zustand setup.
 * Given an explicit level, returns the gate status from FEATURE_GATES.
 */
function resolveGate(featureId: string, level: SkillLevel): GateStatus {
  const gate = FEATURE_GATES[featureId];
  if (!gate) return "visible";
  return gate[level];
}

describe("useFeatureGate — gate resolution logic", () => {
  it("returns 'visible' for a beginner-accessible feature at beginner level", () => {
    // widget:dashboard is visible at every skill level.
    expect(resolveGate("widget:dashboard", "beginner")).toBe("visible");
    // Sanity check: also visible for other levels.
    expect(resolveGate("widget:chart", "intermediate")).toBe("visible");
    expect(resolveGate("widget:watchlist", "advanced")).toBe("visible");
  });

  it("returns 'locked' for an advanced-only feature when the user is beginner", () => {
    // widget:greeks requires advanced — both beginner and intermediate are locked.
    expect(resolveGate("widget:greeks", "beginner")).toBe("locked");
    expect(resolveGate("widget:greeks", "intermediate")).toBe("locked");
    // Advanced users see it as visible.
    expect(resolveGate("widget:greeks", "advanced")).toBe("visible");
  });

  it("gates the Wave-35 order-flow widgets so they unlock at advanced (not perma-locked)", () => {
    // footprint + domheatmap were registered + in the advanced tier but had NO
    // FEATURE_GATES entry, so the picker rendered them locked. They must resolve
    // to a real gate (advanced=visible), not the unknown-feature fallback.
    for (const id of ["widget:footprint", "widget:domheatmap"]) {
      expect(FEATURE_GATES[id]).toBeDefined();
      expect(resolveGate(id, "advanced")).toBe("visible");
      expect(resolveGate(id, "beginner")).toBe("locked");
    }
  });

  it("returns 'preview' for a beginner-preview feature when the user is beginner", () => {
    // route:lab is 'preview' for beginners, 'visible' for intermediate/advanced.
    expect(resolveGate("route:lab", "beginner")).toBe("preview");
    expect(resolveGate("route:lab", "intermediate")).toBe("visible");
    expect(resolveGate("route:lab", "advanced")).toBe("visible");
  });

  it("returns 'visible' when the effective level is elevated by a route override", () => {
    // Simulate: user is globally beginner, but the trade domain override is
    // intermediate.  At intermediate, widget:scalper becomes visible.
    const globalLevel: SkillLevel = "beginner";
    const tradeOverride: SkillLevel = "intermediate";

    // Reproduce getEffectiveLevel logic: override wins over global.
    const effectiveLevel: SkillLevel = tradeOverride ?? globalLevel;

    expect(resolveGate("widget:scalper", effectiveLevel)).toBe("visible");
    // Confirm the same feature is locked at the un-overridden global level.
    expect(resolveGate("widget:scalper", globalLevel)).toBe("locked");
  });

  it("returns 'visible' for an unknown feature ID (graceful default)", () => {
    // Unknown features must never throw and must default to visible so that
    // features added to the codebase before a gate entry is written stay usable.
    expect(resolveGate("feature:does-not-exist-yet", "beginner")).toBe("visible");
    expect(resolveGate("widget:future-widget", "intermediate")).toBe("visible");
    expect(resolveGate("", "advanced")).toBe("visible");
  });
});
