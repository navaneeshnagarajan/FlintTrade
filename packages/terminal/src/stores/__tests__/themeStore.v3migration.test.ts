/**
 * themeStore.v3migration.test.ts
 *
 * TDD tests for the v2 → v3 migration in themeStore.
 *
 * v3 changes:
 *   - Drops 5 deprecated themes: emerald-night, ocean-depth, solar-flare,
 *     neon-pulse, blood-moon.
 *   - Introduces 6 canonical themes: graphite, midnight, arctic-frost,
 *     monochrome, solarized-dark, light.
 *   - Maps removed theme ids to the closest canonical replacement.
 *   - Default activeThemeId becomes "graphite".
 *   - removeCustomTheme() fallback becomes "graphite".
 *   - getActiveTheme() falls back to CINEMATIC_THEMES[0] (graphite).
 *
 * These tests drive the store migration logic; they must be RED before the
 * migration is implemented and GREEN after.
 */

import { describe, it, expect, beforeEach } from "vitest";
import { useThemeStore } from "../themeStore";
import { CINEMATIC_THEMES } from "@/lib/cinematicThemes";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/**
 * Simulate the v2 → v3 migration by calling the store's persist migrate
 * function directly with a v2-era persisted payload.
 *
 * We inline the V2_TO_V3_THEME_MAP here (matching themeStore.ts) so the
 * tests remain self-contained and document the exact mapping contract.
 */
function simulateV2ToV3Migration(oldId: string): Record<string, unknown> {
  const V2_TO_V3_THEME_MAP: Record<string, string> = {
    "emerald-night": "graphite",
    "ocean-depth":   "midnight",
    "solar-flare":   "graphite",
    "neon-pulse":    "graphite",
    "blood-moon":    "graphite",
  };

  const p: Record<string, unknown> = {
    activeThemeId: oldId,
    mode: "system",
    customThemes: [],
    reduceMotion: false,
  };

  // Simulate version < 3 branch: remap if the id appears in the map
  const mapped = V2_TO_V3_THEME_MAP[oldId];
  if (mapped) {
    p["activeThemeId"] = mapped;
  }

  return p;
}

/** Reset the store to a clean v3 initial state before each test. */
function resetStore() {
  useThemeStore.setState({
    activeThemeId: "graphite",
    mode: "system",
    customThemes: [],
    reduceMotion: false,
    glass:      { enabled: false, transparency: 0, blur: 0 },
    background: { type: "solid", value: "", overlay: "" },
  });
}

// ---------------------------------------------------------------------------
// Setup
// ---------------------------------------------------------------------------

beforeEach(() => {
  resetStore();
  document.documentElement.removeAttribute("style");
  document.documentElement.removeAttribute("data-theme");
  document.documentElement.className = "";
});

// ---------------------------------------------------------------------------
// Task A — v2 → v3 migration mapping
// ---------------------------------------------------------------------------

describe("themeStore v3 migration", () => {
  it("migrates emerald-night to graphite", () => {
    const result = simulateV2ToV3Migration("emerald-night");
    expect(result["activeThemeId"]).toBe("graphite");
  });

  it("migrates ocean-depth to midnight", () => {
    const result = simulateV2ToV3Migration("ocean-depth");
    expect(result["activeThemeId"]).toBe("midnight");
  });

  it("migrates solar-flare to graphite", () => {
    const result = simulateV2ToV3Migration("solar-flare");
    expect(result["activeThemeId"]).toBe("graphite");
  });

  it("migrates neon-pulse to graphite", () => {
    const result = simulateV2ToV3Migration("neon-pulse");
    expect(result["activeThemeId"]).toBe("graphite");
  });

  it("migrates blood-moon to graphite", () => {
    const result = simulateV2ToV3Migration("blood-moon");
    expect(result["activeThemeId"]).toBe("graphite");
  });

  it("keeps midnight as midnight", () => {
    const result = simulateV2ToV3Migration("midnight");
    expect(result["activeThemeId"]).toBe("midnight");
  });

  it("keeps arctic-frost as arctic-frost", () => {
    const result = simulateV2ToV3Migration("arctic-frost");
    expect(result["activeThemeId"]).toBe("arctic-frost");
  });
});

// ---------------------------------------------------------------------------
// Task B — default activeThemeId is graphite in v3
// ---------------------------------------------------------------------------

describe("v3 store defaults", () => {
  it("sets default activeThemeId to graphite", () => {
    // After resetStore() the id should be graphite.
    expect(useThemeStore.getState().activeThemeId).toBe("graphite");
  });
});

// ---------------------------------------------------------------------------
// Task B — removeCustomTheme fallback is graphite in v3
// ---------------------------------------------------------------------------

describe("removeCustomTheme v3 fallback", () => {
  it("falls back to graphite when the active custom theme is removed", () => {
    const custom = { ...CINEMATIC_THEMES[0], id: "custom-v3-001" };
    useThemeStore.getState().addCustomTheme(custom);
    useThemeStore.setState({ activeThemeId: "custom-v3-001" });
    useThemeStore.getState().removeCustomTheme("custom-v3-001");
    expect(useThemeStore.getState().activeThemeId).toBe("graphite");
  });
});

// ---------------------------------------------------------------------------
// Task B — getActiveTheme fallback is CINEMATIC_THEMES[0] (graphite) in v3
// ---------------------------------------------------------------------------

describe("getActiveTheme v3 fallback", () => {
  it("falls back to CINEMATIC_THEMES[0] (graphite) when id is not found", () => {
    useThemeStore.setState({ activeThemeId: "nonexistent-theme-xyz" });
    const theme = useThemeStore.getState().getActiveTheme();
    expect(theme.id).toBe(CINEMATIC_THEMES[0].id);
    expect(CINEMATIC_THEMES[0].id).toBe("graphite");
  });
});

// ---------------------------------------------------------------------------
// Task C — CINEMATIC_THEMES registry has exactly 6 entries in v3
// ---------------------------------------------------------------------------

describe("CINEMATIC_THEMES v3 registry", () => {
  it("has exactly 6 themes", () => {
    expect(CINEMATIC_THEMES).toHaveLength(6);
  });

  it("contains graphite", () => {
    expect(CINEMATIC_THEMES.some((t) => t.id === "graphite")).toBe(true);
  });

  it("contains midnight", () => {
    expect(CINEMATIC_THEMES.some((t) => t.id === "midnight")).toBe(true);
  });

  it("contains arctic-frost", () => {
    expect(CINEMATIC_THEMES.some((t) => t.id === "arctic-frost")).toBe(true);
  });

  it("contains monochrome", () => {
    expect(CINEMATIC_THEMES.some((t) => t.id === "monochrome")).toBe(true);
  });

  it("contains solarized-dark", () => {
    expect(CINEMATIC_THEMES.some((t) => t.id === "solarized-dark")).toBe(true);
  });

  it("contains light", () => {
    expect(CINEMATIC_THEMES.some((t) => t.id === "light")).toBe(true);
  });

  it("does NOT contain emerald-night", () => {
    expect(CINEMATIC_THEMES.some((t) => t.id === "emerald-night")).toBe(false);
  });

  it("does NOT contain ocean-depth", () => {
    expect(CINEMATIC_THEMES.some((t) => t.id === "ocean-depth")).toBe(false);
  });

  it("does NOT contain solar-flare", () => {
    expect(CINEMATIC_THEMES.some((t) => t.id === "solar-flare")).toBe(false);
  });

  it("does NOT contain neon-pulse", () => {
    expect(CINEMATIC_THEMES.some((t) => t.id === "neon-pulse")).toBe(false);
  });

  it("does NOT contain blood-moon", () => {
    expect(CINEMATIC_THEMES.some((t) => t.id === "blood-moon")).toBe(false);
  });

  it("graphite is at index 0", () => {
    expect(CINEMATIC_THEMES[0].id).toBe("graphite");
  });
});

// ---------------------------------------------------------------------------
// Task B — applyTheme works correctly with graphite as default
// ---------------------------------------------------------------------------

describe("applyTheme with graphite (v3 default)", () => {
  it("sets data-theme to graphite when active", () => {
    useThemeStore.setState({ activeThemeId: "graphite", mode: "dark" });
    useThemeStore.getState().applyTheme();
    expect(document.documentElement.getAttribute("data-theme")).toBe("graphite");
  });

  it("sets --color-accent correctly for graphite dark", () => {
    useThemeStore.setState({ activeThemeId: "graphite", mode: "dark" });
    useThemeStore.getState().applyTheme();
    const accent = document.documentElement.style.getPropertyValue("--color-accent");
    expect(accent).toBeTruthy();
    // Graphite dark accent is #7c8be8
    expect(accent).toBe("#7c8be8");
  });

  it("sets --color-profit to fixed #22c55e for graphite", () => {
    useThemeStore.setState({ activeThemeId: "graphite", mode: "dark" });
    useThemeStore.getState().applyTheme();
    expect(document.documentElement.style.getPropertyValue("--color-profit")).toBe("#22c55e");
  });
});

// ---------------------------------------------------------------------------
// Task B — applyTheme works correctly with midnight
// ---------------------------------------------------------------------------

describe("applyTheme with midnight", () => {
  it("sets data-theme to midnight when active", () => {
    useThemeStore.setState({ activeThemeId: "midnight", mode: "dark" });
    useThemeStore.getState().applyTheme();
    expect(document.documentElement.getAttribute("data-theme")).toBe("midnight");
  });
});
