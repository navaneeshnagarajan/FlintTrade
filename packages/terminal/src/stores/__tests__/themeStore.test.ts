/**
 * themeStore.test.ts
 *
 * Tests for themeStore v4 — 3 themes (graphite, midnight, ember),
 * glass as boolean, trading semantics in ThemeVariant, system mode
 * matchMedia listener, and applyTheme CSS property writes.
 */

import { describe, it, expect, beforeEach, vi, afterEach } from "vitest";
import { useThemeStore } from "../themeStore";
import { CINEMATIC_THEMES } from "@/lib/cinematicThemes";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Reset the store to v4 initial state before each test. */
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
// Setup / teardown
// ---------------------------------------------------------------------------

beforeEach(() => {
  resetStore();
  document.documentElement.removeAttribute("style");
  document.documentElement.removeAttribute("data-theme");
  document.documentElement.className = "";
});

afterEach(() => {
  vi.restoreAllMocks();
});

// ---------------------------------------------------------------------------
// Default state
// ---------------------------------------------------------------------------

describe("default state", () => {
  it("activeThemeId defaults to graphite", () => {
    expect(useThemeStore.getState().activeThemeId).toBe("graphite");
  });

  it("mode defaults to system", () => {
    expect(useThemeStore.getState().mode).toBe("system");
  });

  it("reduceMotion defaults to false", () => {
    expect(useThemeStore.getState().reduceMotion).toBe(false);
  });

  it("customThemes defaults to empty array", () => {
    expect(useThemeStore.getState().customThemes).toEqual([]);
  });

  it("glass defaults to true (enabled)", () => {
    expect(useThemeStore.getState().glass).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// v4 migration mapping (inline simulation)
// ---------------------------------------------------------------------------

describe("v4 migration mapping", () => {
  function simulateMigration(oldId: string): string {
    const ALL_LEGACY_TO_V4: Record<string, string> = {
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
      "emerald-night":    "graphite",
      "ocean-depth":      "midnight",
      "solar-flare":      "ember",
      "neon-pulse":       "graphite",
      "blood-moon":       "ember",
      "arctic-frost":     "graphite",
    };
    return ALL_LEGACY_TO_V4[oldId] ?? "graphite";
  }

  it("maps midnight → midnight", () => {
    expect(simulateMigration("midnight")).toBe("midnight");
  });

  it("maps obsidian → graphite", () => {
    expect(simulateMigration("obsidian")).toBe("graphite");
  });

  it("maps terminal-green → graphite", () => {
    expect(simulateMigration("terminal-green")).toBe("graphite");
  });

  it("maps ocean-blue → midnight", () => {
    expect(simulateMigration("ocean-blue")).toBe("midnight");
  });

  it("maps sunset → ember", () => {
    expect(simulateMigration("sunset")).toBe("ember");
  });

  it("maps solar-flare → ember", () => {
    expect(simulateMigration("solar-flare")).toBe("ember");
  });

  it("maps blood-moon → ember", () => {
    expect(simulateMigration("blood-moon")).toBe("ember");
  });

  it("maps arctic-frost → graphite", () => {
    expect(simulateMigration("arctic-frost")).toBe("graphite");
  });

  it("maps monochrome → graphite", () => {
    expect(simulateMigration("monochrome")).toBe("graphite");
  });

  it("maps emerald-night → graphite", () => {
    expect(simulateMigration("emerald-night")).toBe("graphite");
  });

  it("maps unknown id → graphite", () => {
    expect(simulateMigration("unknown-theme")).toBe("graphite");
  });
});

// ---------------------------------------------------------------------------
// getActiveTheme
// ---------------------------------------------------------------------------

describe("getActiveTheme", () => {
  it("returns a CinematicTheme object for the default id", () => {
    const theme = useThemeStore.getState().getActiveTheme();
    expect(theme.id).toBe("graphite");
    expect(theme.dark).toBeDefined();
    expect(theme.light).toBeDefined();
    expect(theme.shared).toBeDefined();
  });

  it("returns the correct theme after setTheme to midnight", () => {
    useThemeStore.getState().setTheme("midnight");
    expect(useThemeStore.getState().getActiveTheme().id).toBe("midnight");
  });

  it("returns the correct theme after setTheme to ember", () => {
    useThemeStore.getState().setTheme("ember");
    expect(useThemeStore.getState().getActiveTheme().id).toBe("ember");
  });

  it("falls back to graphite (CINEMATIC_THEMES[0]) if id is not found", () => {
    useThemeStore.setState({ activeThemeId: "nonexistent" });
    const theme = useThemeStore.getState().getActiveTheme();
    expect(theme.id).toBe("graphite");
  });

  it("finds custom theme when present", () => {
    const customTheme = { ...CINEMATIC_THEMES[0], id: "custom-test-001" };
    useThemeStore.getState().addCustomTheme(customTheme);
    useThemeStore.setState({ activeThemeId: "custom-test-001" });
    expect(useThemeStore.getState().getActiveTheme().id).toBe("custom-test-001");
  });
});

// ---------------------------------------------------------------------------
// getResolvedMode
// ---------------------------------------------------------------------------

describe("getResolvedMode", () => {
  it("returns dark when mode is dark", () => {
    useThemeStore.setState({ mode: "dark" });
    expect(useThemeStore.getState().getResolvedMode()).toBe("dark");
  });

  it("returns light when mode is light", () => {
    useThemeStore.setState({ mode: "light" });
    expect(useThemeStore.getState().getResolvedMode()).toBe("light");
  });

  it("returns dark for system when matchMedia reports dark", () => {
    vi.spyOn(window, "matchMedia").mockImplementation((query) => ({
      matches:             query === "(prefers-color-scheme: dark)",
      media:               query,
      onchange:            null,
      addListener:         vi.fn(),
      removeListener:      vi.fn(),
      addEventListener:    vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent:       vi.fn(),
    }));
    useThemeStore.setState({ mode: "system" });
    expect(useThemeStore.getState().getResolvedMode()).toBe("dark");
  });

  it("returns light for system when matchMedia reports light", () => {
    vi.spyOn(window, "matchMedia").mockImplementation((query) => ({
      matches:             query !== "(prefers-color-scheme: dark)",
      media:               query,
      onchange:            null,
      addListener:         vi.fn(),
      removeListener:      vi.fn(),
      addEventListener:    vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent:       vi.fn(),
    }));
    useThemeStore.setState({ mode: "system" });
    expect(useThemeStore.getState().getResolvedMode()).toBe("light");
  });
});

// ---------------------------------------------------------------------------
// setTheme
// ---------------------------------------------------------------------------

describe("setTheme", () => {
  it("updates activeThemeId to midnight", () => {
    useThemeStore.getState().setTheme("midnight");
    expect(useThemeStore.getState().activeThemeId).toBe("midnight");
  });

  it("updates activeThemeId to ember", () => {
    useThemeStore.getState().setTheme("ember");
    expect(useThemeStore.getState().activeThemeId).toBe("ember");
  });

  it("calls applyTheme (sets data-theme attribute)", () => {
    useThemeStore.getState().setTheme("midnight");
    expect(document.documentElement.getAttribute("data-theme")).toBe("midnight");
  });

  it("sets all 3 canonical theme ids without error", () => {
    for (const t of CINEMATIC_THEMES) {
      expect(() => useThemeStore.getState().setTheme(t.id)).not.toThrow();
    }
  });
});

// ---------------------------------------------------------------------------
// setMode
// ---------------------------------------------------------------------------

describe("setMode", () => {
  it("updates mode to dark", () => {
    useThemeStore.getState().setMode("dark");
    expect(useThemeStore.getState().mode).toBe("dark");
  });

  it("updates mode to light", () => {
    useThemeStore.getState().setMode("light");
    expect(useThemeStore.getState().mode).toBe("light");
  });

  it("updates mode to system", () => {
    useThemeStore.setState({ mode: "dark" });
    useThemeStore.getState().setMode("system");
    expect(useThemeStore.getState().mode).toBe("system");
  });

  it("adds theme-light class when mode changes to light", () => {
    useThemeStore.getState().setMode("light");
    expect(document.documentElement.classList.contains("theme-light")).toBe(true);
  });

  it("removes theme-light class when mode changes to dark", () => {
    document.documentElement.classList.add("theme-light");
    useThemeStore.getState().setMode("dark");
    expect(document.documentElement.classList.contains("theme-light")).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// setGlass
// ---------------------------------------------------------------------------

describe("setGlass", () => {
  it("can be set to false (disables glass)", () => {
    useThemeStore.getState().setGlass(false);
    expect(useThemeStore.getState().glass).toBe(false);
  });

  it("can be set to true (enables glass)", () => {
    useThemeStore.setState({ glass: false });
    useThemeStore.getState().setGlass(true);
    expect(useThemeStore.getState().glass).toBe(true);
  });

  it("sets --glass-blur to 0 when glass disabled", () => {
    useThemeStore.setState({ activeThemeId: "graphite", mode: "dark" });
    useThemeStore.getState().setGlass(false);
    expect(document.documentElement.style.getPropertyValue("--glass-blur")).toBe("0px");
  });

  it("sets --glass-blur to theme value when glass enabled", () => {
    useThemeStore.setState({ activeThemeId: "graphite", mode: "dark" });
    useThemeStore.getState().setGlass(true);
    const blur = document.documentElement.style.getPropertyValue("--glass-blur");
    expect(blur).not.toBe("0px");
    expect(blur).toBeTruthy();
  });
});

// ---------------------------------------------------------------------------
// applyTheme — CSS property writes
// ---------------------------------------------------------------------------

describe("applyTheme CSS properties", () => {
  beforeEach(() => {
    useThemeStore.setState({ activeThemeId: "graphite", mode: "dark", glass: true });
    useThemeStore.getState().applyTheme();
  });

  it("sets --color-base", () => {
    expect(document.documentElement.style.getPropertyValue("--color-base")).toBeTruthy();
  });

  it("sets --color-card", () => {
    expect(document.documentElement.style.getPropertyValue("--color-card")).toBeTruthy();
  });

  it("sets --color-accent for graphite dark (emerald green)", () => {
    const accent = document.documentElement.style.getPropertyValue("--color-accent");
    expect(accent).toBeTruthy();
    // Graphite dark accent is #22c55e (emerald-500)
    expect(accent).toBe("#22c55e");
  });

  it("sets --color-profit to fixed #22c55e regardless of theme", () => {
    useThemeStore.getState().setTheme("midnight");
    expect(document.documentElement.style.getPropertyValue("--color-profit")).toBe("#22c55e");
  });

  it("sets --color-loss to fixed #ef4444 regardless of theme", () => {
    useThemeStore.getState().setTheme("ember");
    expect(document.documentElement.style.getPropertyValue("--color-loss")).toBe("#ef4444");
  });

  it("sets --color-warning to fixed #f59e0b regardless of theme", () => {
    useThemeStore.getState().setTheme("midnight");
    expect(document.documentElement.style.getPropertyValue("--color-warning")).toBe("#f59e0b");
  });

  it("sets --particle-primary", () => {
    expect(document.documentElement.style.getPropertyValue("--particle-primary")).toBeTruthy();
  });

  it("sets --glass-tint", () => {
    expect(document.documentElement.style.getPropertyValue("--glass-tint")).toBeTruthy();
  });

  it("sets --glow-color", () => {
    expect(document.documentElement.style.getPropertyValue("--glow-color")).toBeTruthy();
  });

  it("sets --shimmer-color", () => {
    expect(document.documentElement.style.getPropertyValue("--shimmer-color")).toBeTruthy();
  });

  it("sets --shimmer-speed", () => {
    expect(document.documentElement.style.getPropertyValue("--shimmer-speed")).toBeTruthy();
  });

  it("sets --chart-color-1 through --chart-color-5", () => {
    for (let i = 1; i <= 5; i++) {
      expect(document.documentElement.style.getPropertyValue(`--chart-color-${i}`)).toBeTruthy();
    }
  });

  it("sets --scrollbar-thumb", () => {
    expect(document.documentElement.style.getPropertyValue("--scrollbar-thumb")).toBeTruthy();
  });

  it("sets --focus-ring", () => {
    expect(document.documentElement.style.getPropertyValue("--focus-ring")).toBeTruthy();
  });

  it("sets --skeleton-shimmer", () => {
    expect(document.documentElement.style.getPropertyValue("--skeleton-shimmer")).toBeTruthy();
  });

  it("sets data-theme attribute to theme id", () => {
    expect(document.documentElement.getAttribute("data-theme")).toBe("graphite");
  });

  it("adds theme-light class in light mode", () => {
    useThemeStore.setState({ mode: "light" });
    useThemeStore.getState().applyTheme();
    expect(document.documentElement.classList.contains("theme-light")).toBe(true);
  });

  it("removes theme-light class in dark mode", () => {
    document.documentElement.classList.add("theme-light");
    useThemeStore.setState({ mode: "dark" });
    useThemeStore.getState().applyTheme();
    expect(document.documentElement.classList.contains("theme-light")).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// setReduceMotion
// ---------------------------------------------------------------------------

describe("setReduceMotion", () => {
  it("sets reduceMotion to true and adds class", () => {
    useThemeStore.getState().setReduceMotion(true);
    expect(useThemeStore.getState().reduceMotion).toBe(true);
    expect(document.documentElement.classList.contains("reduce-motion")).toBe(true);
  });

  it("sets reduceMotion to false and removes class", () => {
    document.documentElement.classList.add("reduce-motion");
    useThemeStore.getState().setReduceMotion(false);
    expect(useThemeStore.getState().reduceMotion).toBe(false);
    expect(document.documentElement.classList.contains("reduce-motion")).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// Custom themes
// ---------------------------------------------------------------------------

describe("custom themes", () => {
  it("addCustomTheme stores the theme", () => {
    const custom = { ...CINEMATIC_THEMES[0], id: "custom-001" };
    useThemeStore.getState().addCustomTheme(custom);
    expect(useThemeStore.getState().customThemes.some((t) => t.id === "custom-001")).toBe(true);
  });

  it("addCustomTheme replaces theme with same id", () => {
    const v1 = { ...CINEMATIC_THEMES[0], id: "custom-001", name: "V1" };
    const v2 = { ...CINEMATIC_THEMES[0], id: "custom-001", name: "V2" };
    useThemeStore.getState().addCustomTheme(v1);
    useThemeStore.getState().addCustomTheme(v2);
    const all = useThemeStore.getState().customThemes.filter((t) => t.id === "custom-001");
    expect(all).toHaveLength(1);
    expect(all[0].name).toBe("V2");
  });

  it("removeCustomTheme removes the theme", () => {
    const custom = { ...CINEMATIC_THEMES[0], id: "custom-002" };
    useThemeStore.getState().addCustomTheme(custom);
    useThemeStore.getState().removeCustomTheme("custom-002");
    expect(useThemeStore.getState().customThemes.some((t) => t.id === "custom-002")).toBe(false);
  });

  it("removeCustomTheme falls back to graphite when active theme removed", () => {
    const custom = { ...CINEMATIC_THEMES[0], id: "custom-003" };
    useThemeStore.getState().addCustomTheme(custom);
    useThemeStore.setState({ activeThemeId: "custom-003" });
    useThemeStore.getState().removeCustomTheme("custom-003");
    expect(useThemeStore.getState().activeThemeId).toBe("graphite");
  });
});
