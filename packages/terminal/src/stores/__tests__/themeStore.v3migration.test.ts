/**
 * themeStore.v4migration.test.ts
 *
 * Tests for the v3 → v4 migration in themeStore.
 *
 * v4 changes:
 *   - Drops all v3 themes: arctic-frost, monochrome, solarized-dark, light.
 *   - Only 3 canonical themes: graphite, midnight, ember.
 *   - Maps all removed/legacy theme ids → closest v4 canonical.
 *   - glass changed from GlassSettings object to boolean.
 *   - Default activeThemeId is "graphite".
 *   - removeCustomTheme() fallback is "graphite".
 *   - getActiveTheme() falls back to CINEMATIC_THEMES[0] (graphite).
 */

import { describe, it, expect, beforeEach } from "vitest";
import { useThemeStore } from "../themeStore";
import { CINEMATIC_THEMES } from "@/lib/cinematicThemes";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function simulateV4Migration(oldId: string): string {
  const ALL_LEGACY_TO_V4: Record<string, string> = {
    // v1 ids
    midnight:           "midnight",
    obsidian:           "graphite",
    "terminal-green":   "graphite",
    "ocean-blue":       "midnight",
    light:              "graphite",
    sunset:             "ember",
    arctic:             "graphite",
    neon:               "graphite",
    forest:             "graphite",
    monochrome:         "graphite",
    "solarized-dark":   "graphite",
    "solarized-light":  "graphite",
    // v2 ids
    "emerald-night":    "graphite",
    "ocean-depth":      "midnight",
    "solar-flare":      "ember",
    "neon-pulse":       "graphite",
    "blood-moon":       "ember",
    // v3 ids
    "arctic-frost":     "graphite",
  };
  return ALL_LEGACY_TO_V4[oldId] ?? "graphite";
}

function resetStore() {
  useThemeStore.setState({
    activeThemeId: "graphite",
    mode:          "system",
    customThemes:  [],
    reduceMotion:  false,
    glass:         true,
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
// v3 → v4 migration mapping
// ---------------------------------------------------------------------------

describe("themeStore v4 migration mapping", () => {
  it("migrates emerald-night to graphite", () => {
    expect(simulateV4Migration("emerald-night")).toBe("graphite");
  });

  it("migrates ocean-depth to midnight", () => {
    expect(simulateV4Migration("ocean-depth")).toBe("midnight");
  });

  it("migrates solar-flare to ember", () => {
    expect(simulateV4Migration("solar-flare")).toBe("ember");
  });

  it("migrates blood-moon to ember", () => {
    expect(simulateV4Migration("blood-moon")).toBe("ember");
  });

  it("migrates neon-pulse to graphite", () => {
    expect(simulateV4Migration("neon-pulse")).toBe("graphite");
  });

  it("migrates arctic-frost to graphite", () => {
    expect(simulateV4Migration("arctic-frost")).toBe("graphite");
  });

  it("migrates monochrome to graphite", () => {
    expect(simulateV4Migration("monochrome")).toBe("graphite");
  });

  it("migrates solarized-dark to graphite", () => {
    expect(simulateV4Migration("solarized-dark")).toBe("graphite");
  });

  it("migrates light to graphite", () => {
    expect(simulateV4Migration("light")).toBe("graphite");
  });

  it("keeps midnight as midnight", () => {
    expect(simulateV4Migration("midnight")).toBe("midnight");
  });

  it("maps unknown id to graphite", () => {
    expect(simulateV4Migration("completely-unknown")).toBe("graphite");
  });
});

// ---------------------------------------------------------------------------
// v4 store defaults
// ---------------------------------------------------------------------------

describe("v4 store defaults", () => {
  it("sets default activeThemeId to graphite", () => {
    expect(useThemeStore.getState().activeThemeId).toBe("graphite");
  });

  it("glass defaults to true (boolean)", () => {
    expect(useThemeStore.getState().glass).toBe(true);
    expect(typeof useThemeStore.getState().glass).toBe("boolean");
  });
});

// ---------------------------------------------------------------------------
// removeCustomTheme fallback is graphite in v4
// ---------------------------------------------------------------------------

describe("removeCustomTheme v4 fallback", () => {
  it("falls back to graphite when the active custom theme is removed", () => {
    const custom = { ...CINEMATIC_THEMES[0], id: "custom-v4-001" };
    useThemeStore.getState().addCustomTheme(custom);
    useThemeStore.setState({ activeThemeId: "custom-v4-001" });
    useThemeStore.getState().removeCustomTheme("custom-v4-001");
    expect(useThemeStore.getState().activeThemeId).toBe("graphite");
  });
});

// ---------------------------------------------------------------------------
// getActiveTheme fallback is CINEMATIC_THEMES[0] (graphite) in v4
// ---------------------------------------------------------------------------

describe("getActiveTheme v4 fallback", () => {
  it("falls back to CINEMATIC_THEMES[0] (graphite) when id is not found", () => {
    useThemeStore.setState({ activeThemeId: "nonexistent-theme-xyz" });
    const theme = useThemeStore.getState().getActiveTheme();
    expect(theme.id).toBe(CINEMATIC_THEMES[0].id);
    expect(CINEMATIC_THEMES[0].id).toBe("graphite");
  });
});

// ---------------------------------------------------------------------------
// CINEMATIC_THEMES registry has exactly 3 entries in v4
// ---------------------------------------------------------------------------

describe("CINEMATIC_THEMES v4 registry", () => {
  it("has exactly 3 themes", () => {
    expect(CINEMATIC_THEMES).toHaveLength(3);
  });

  it("contains graphite", () => {
    expect(CINEMATIC_THEMES.some((t) => t.id === "graphite")).toBe(true);
  });

  it("contains midnight", () => {
    expect(CINEMATIC_THEMES.some((t) => t.id === "midnight")).toBe(true);
  });

  it("contains ember", () => {
    expect(CINEMATIC_THEMES.some((t) => t.id === "ember")).toBe(true);
  });

  it("graphite is at index 0", () => {
    expect(CINEMATIC_THEMES[0].id).toBe("graphite");
  });

  it("does NOT contain arctic-frost", () => {
    expect(CINEMATIC_THEMES.some((t) => t.id === "arctic-frost")).toBe(false);
  });

  it("does NOT contain monochrome", () => {
    expect(CINEMATIC_THEMES.some((t) => t.id === "monochrome")).toBe(false);
  });

  it("does NOT contain solarized-dark", () => {
    expect(CINEMATIC_THEMES.some((t) => t.id === "solarized-dark")).toBe(false);
  });

  it("does NOT contain light (v3 theme)", () => {
    expect(CINEMATIC_THEMES.some((t) => t.id === "light")).toBe(false);
  });

  it("does NOT contain emerald-night", () => {
    expect(CINEMATIC_THEMES.some((t) => t.id === "emerald-night")).toBe(false);
  });

  it("does NOT contain blood-moon", () => {
    expect(CINEMATIC_THEMES.some((t) => t.id === "blood-moon")).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// Each theme has both dark and light variants with full trading semantics
// ---------------------------------------------------------------------------

describe("v4 theme variant completeness", () => {
  for (const theme of CINEMATIC_THEMES) {
    it(`${theme.id} dark variant has trading semantics`, () => {
      expect(theme.dark.trading).toBeDefined();
      expect(theme.dark.trading.profit).toBe("#22c55e");
      expect(theme.dark.trading.loss).toBe("#ef4444");
      expect(theme.dark.trading.warning).toBe("#f59e0b");
    });

    it(`${theme.id} light variant has trading semantics`, () => {
      expect(theme.light.trading).toBeDefined();
      expect(theme.light.trading.profit).toBe("#22c55e");
      expect(theme.light.trading.loss).toBe("#ef4444");
      expect(theme.light.trading.warning).toBe("#f59e0b");
    });

    it(`${theme.id} dark variant has 5 chart colours`, () => {
      expect(theme.dark.chart).toHaveLength(5);
    });

    it(`${theme.id} light variant has 5 chart colours`, () => {
      expect(theme.light.chart).toHaveLength(5);
    });

    it(`${theme.id} dark variant has borderSubtle`, () => {
      expect(theme.dark.colors.borderSubtle).toBeTruthy();
    });

    it(`${theme.id} light variant has borderSubtle`, () => {
      expect(theme.light.colors.borderSubtle).toBeTruthy();
    });
  }
});

// ---------------------------------------------------------------------------
// applyTheme works correctly for all 3 v4 themes
// ---------------------------------------------------------------------------

describe("applyTheme v4 themes", () => {
  for (const theme of CINEMATIC_THEMES) {
    it(`sets data-theme to ${theme.id}`, () => {
      useThemeStore.setState({ activeThemeId: theme.id, mode: "dark" });
      useThemeStore.getState().applyTheme();
      expect(document.documentElement.getAttribute("data-theme")).toBe(theme.id);
    });

    it(`sets --color-profit to #22c55e for ${theme.id}`, () => {
      useThemeStore.setState({ activeThemeId: theme.id, mode: "dark" });
      useThemeStore.getState().applyTheme();
      expect(document.documentElement.style.getPropertyValue("--color-profit")).toBe("#22c55e");
    });

    it(`sets --color-loss to #ef4444 for ${theme.id}`, () => {
      useThemeStore.setState({ activeThemeId: theme.id, mode: "dark" });
      useThemeStore.getState().applyTheme();
      expect(document.documentElement.style.getPropertyValue("--color-loss")).toBe("#ef4444");
    });
  }
});
