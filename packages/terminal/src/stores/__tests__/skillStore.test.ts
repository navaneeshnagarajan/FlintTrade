import { describe, it, expect, beforeEach } from "vitest";
import { useSkillStore } from "../skillStore";

// Reset to clean defaults before every test so each test is isolated.
beforeEach(() => {
  useSkillStore.getState().resetToDefaults();
});

describe("skillStore", () => {
  // 1. Initial state
  it("initial state has beginner global level", () => {
    expect(useSkillStore.getState().globalLevel).toBe("beginner");
  });

  // 2. setGlobalLevel
  it("setGlobalLevel changes level", () => {
    useSkillStore.getState().setGlobalLevel("advanced");
    expect(useSkillStore.getState().globalLevel).toBe("advanced");
  });

  // 3. setRouteOverride
  it("setRouteOverride sets a per-domain override", () => {
    useSkillStore.getState().setRouteOverride("trade", "intermediate");
    expect(useSkillStore.getState().routeOverrides.trade).toBe("intermediate");
  });

  // 4. clearRouteOverride
  it("clearRouteOverride removes the override for the domain", () => {
    useSkillStore.getState().setRouteOverride("invest", "advanced");
    expect(useSkillStore.getState().routeOverrides.invest).toBe("advanced");
    useSkillStore.getState().clearRouteOverride("invest");
    expect(useSkillStore.getState().routeOverrides.invest).toBeUndefined();
  });

  // 5. getEffectiveLevel — override present
  it("getEffectiveLevel returns the domain override when set", () => {
    useSkillStore.getState().setGlobalLevel("beginner");
    useSkillStore.getState().setRouteOverride("lab", "advanced");
    expect(useSkillStore.getState().getEffectiveLevel("lab")).toBe("advanced");
  });

  // 6. getEffectiveLevel — fallback to global
  it("getEffectiveLevel falls back to globalLevel when no override exists", () => {
    useSkillStore.getState().setGlobalLevel("intermediate");
    // No override for "learn"
    expect(useSkillStore.getState().getEffectiveLevel("learn")).toBe("intermediate");
  });

  // 7. trackAction — valid action
  it("trackAction increments the correct metric", () => {
    expect(useSkillStore.getState().metrics.trade.ordersPlaced).toBe(0);
    useSkillStore.getState().trackAction("trade", "ordersPlaced");
    useSkillStore.getState().trackAction("trade", "ordersPlaced");
    expect(useSkillStore.getState().metrics.trade.ordersPlaced).toBe(2);
  });

  // 8. trackAction — unknown action (no crash, no change)
  it("trackAction ignores unknown action names without throwing", () => {
    const before = useSkillStore.getState().metrics.trade.ordersPlaced;
    expect(() => {
      useSkillStore.getState().trackAction("trade", "nonExistentMetric");
    }).not.toThrow();
    expect(useSkillStore.getState().metrics.trade.ordersPlaced).toBe(before);
  });

  // 9. setHelpPref
  it("setHelpPref toggles individual help preferences", () => {
    // Default is all true
    expect(useSkillStore.getState().helpPrefs.inlineHints).toBe(true);
    useSkillStore.getState().setHelpPref("inlineHints", false);
    expect(useSkillStore.getState().helpPrefs.inlineHints).toBe(false);
    // Other prefs are unaffected
    expect(useSkillStore.getState().helpPrefs.spotlightTours).toBe(true);
    expect(useSkillStore.getState().helpPrefs.aiTutor).toBe(true);
  });

  // 10. dismissSuggestion
  it("dismissSuggestion adds the key to dismissedSuggestions", () => {
    expect(useSkillStore.getState().dismissedSuggestions).toHaveLength(0);
    useSkillStore.getState().dismissSuggestion("trade:intermediate");
    useSkillStore.getState().dismissSuggestion("lab:advanced");
    const { dismissedSuggestions } = useSkillStore.getState();
    expect(dismissedSuggestions).toContain("trade:intermediate");
    expect(dismissedSuggestions).toContain("lab:advanced");
    expect(dismissedSuggestions).toHaveLength(2);
  });

  // 11. resetToDefaults
  it("resetToDefaults restores initial state", () => {
    // Mutate everything
    useSkillStore.getState().setGlobalLevel("advanced");
    useSkillStore.getState().setRouteOverride("ai", "intermediate");
    useSkillStore.getState().setHelpPref("aiTutor", false);
    useSkillStore.getState().trackAction("learn", "lessonsCompleted");
    useSkillStore.getState().dismissSuggestion("ai:advanced");

    useSkillStore.getState().resetToDefaults();

    const state = useSkillStore.getState();
    expect(state.globalLevel).toBe("beginner");
    expect(state.routeOverrides).toEqual({});
    expect(state.helpPrefs.aiTutor).toBe(true);
    expect(state.metrics.learn.lessonsCompleted).toBe(0);
    expect(state.dismissedSuggestions).toHaveLength(0);
  });

  // 12. Persistence to localStorage
  it("store writes to localStorage under the flinttrade:skill key", () => {
    useSkillStore.getState().setGlobalLevel("intermediate");
    // The jsdom environment exposes localStorage; the persist middleware
    // writes synchronously after the state update.
    const raw = localStorage.getItem("flinttrade:skill");
    expect(raw).not.toBeNull();
    const parsed = JSON.parse(raw as string) as { state: { globalLevel: string } };
    expect(parsed.state.globalLevel).toBe("intermediate");
  });
});
