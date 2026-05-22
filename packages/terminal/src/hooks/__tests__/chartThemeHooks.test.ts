/**
 * chartThemeHooks.test.ts
 *
 * Tests for the 5 chart-theme hooks:
 *   - useLightweightChartTheme
 *   - usePlotlyTheme
 *   - useTremorTheme
 *   - useGlideTheme
 *   - useDockviewTheme
 *
 * Strategy:
 *   - Mock getComputedStyle to return deterministic CSS var values
 *   - Mock themeStore so activeThemeId / resolvedMode can be controlled
 *   - Assert all hooks return non-empty objects with the expected shape
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook } from "@testing-library/react";

// ---------------------------------------------------------------------------
// Mock getComputedStyle
// ---------------------------------------------------------------------------

const CSS_VARS: Record<string, string> = {
  "--chart-bg":              "#0a0a0f",
  "--chart-grid":            "#1e1e2e",
  "--chart-text":            "#a0a0b0",
  "--chart-up":              "#22c55e",
  "--chart-down":            "#ef4444",
  "--color-accent":          "#6366f1",
  "--color-profit":          "#22c55e",
  "--color-loss":            "#ef4444",
  "--color-warning":         "#f59e0b",
  "--color-accent-muted":    "#818cf8",
  "--color-text-secondary":  "#8b8b95",
  "--color-base":            "#0a0a0f",
  "--color-card":            "#16161f",
  "--color-hover":           "#24242e",
  "--color-border":          "#2a2a3a",
  "--color-text":            "#e4e4e7",
  "--color-text-muted":      "#6b6b78",
};

beforeEach(() => {
  vi.stubGlobal(
    "getComputedStyle",
    () => ({
      getPropertyValue: (prop: string) => CSS_VARS[prop] ?? "",
    }),
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
});

// ---------------------------------------------------------------------------
// Mock themeStore
// ---------------------------------------------------------------------------

vi.mock("@/stores/themeStore", () => ({
  useThemeStore: (selector: (s: { activeThemeId: string; getResolvedMode: () => "dark" | "light" }) => unknown) => {
    return selector({
      activeThemeId: "emerald-night",
      getResolvedMode: () => "dark",
    });
  },
}));

// ---------------------------------------------------------------------------
// Import hooks AFTER mocks are set up
// ---------------------------------------------------------------------------

import { useLightweightChartTheme } from "../useChartTheme";
import { usePlotlyTheme } from "../usePlotlyTheme";
import { useTremorTheme } from "../useTremorTheme";
import { useGlideTheme } from "../useGlideTheme";
import { useDockviewTheme } from "../useDockviewTheme";

// ---------------------------------------------------------------------------
// useLightweightChartTheme
// ---------------------------------------------------------------------------

describe("useLightweightChartTheme", () => {
  it("returns a non-empty object", () => {
    const { result } = renderHook(() => useLightweightChartTheme());
    expect(result.current).toBeTruthy();
    expect(typeof result.current).toBe("object");
  });

  it("has required layout keys", () => {
    const { result } = renderHook(() => useLightweightChartTheme());
    const theme = result.current;
    expect(theme.layout).toBeDefined();
    expect(theme.layout?.background).toBeDefined();
    expect(typeof theme.layout?.textColor).toBe("string");
    expect(theme.layout?.textColor).toBeTruthy();
  });

  it("has grid configuration", () => {
    const { result } = renderHook(() => useLightweightChartTheme());
    expect(theme(result).grid?.vertLines?.color).toBeTruthy();
    expect(theme(result).grid?.horzLines?.color).toBeTruthy();
  });

  it("has candle colors (up and down)", () => {
    const { result } = renderHook(() => useLightweightChartTheme());
    expect(result.current.candle.upColor).toBeTruthy();
    expect(result.current.candle.downColor).toBeTruthy();
    expect(result.current.candle.upColor).not.toBe(result.current.candle.downColor);
  });

  it("reads --chart-up from CSS vars", () => {
    const { result } = renderHook(() => useLightweightChartTheme());
    expect(result.current.candle.upColor).toBe("#22c55e");
  });

  it("reads --chart-down from CSS vars", () => {
    const { result } = renderHook(() => useLightweightChartTheme());
    expect(result.current.candle.downColor).toBe("#ef4444");
  });

  it("has timeScale configuration", () => {
    const { result } = renderHook(() => useLightweightChartTheme());
    expect(theme(result).timeScale?.timeVisible).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// usePlotlyTheme
// ---------------------------------------------------------------------------

describe("usePlotlyTheme", () => {
  it("returns a non-empty object", () => {
    const { result } = renderHook(() => usePlotlyTheme());
    expect(result.current).toBeTruthy();
    expect(typeof result.current).toBe("object");
    expect(Object.keys(result.current).length).toBeGreaterThan(0);
  });

  it("has transparent backgrounds for overlay use", () => {
    const { result } = renderHook(() => usePlotlyTheme());
    expect(result.current.paper_bgcolor).toBe("transparent");
    expect(result.current.plot_bgcolor).toBe("transparent");
  });

  it("has font configuration", () => {
    const { result } = renderHook(() => usePlotlyTheme());
    expect(result.current.font?.color).toBeTruthy();
    expect(result.current.font?.family).toContain("Inter");
  });

  it("has xaxis and yaxis grid colors", () => {
    const { result } = renderHook(() => usePlotlyTheme());
    expect(result.current.xaxis?.gridcolor).toBeTruthy();
    expect(result.current.yaxis?.gridcolor).toBeTruthy();
  });

  it("has a colorway with at least 3 entries", () => {
    const { result } = renderHook(() => usePlotlyTheme());
    expect(Array.isArray(result.current.colorway)).toBe(true);
    expect((result.current.colorway as string[]).length).toBeGreaterThanOrEqual(3);
  });

  it("colorway includes accent, profit, and loss colors", () => {
    const { result } = renderHook(() => usePlotlyTheme());
    const cw = result.current.colorway as string[];
    expect(cw).toContain("#6366f1"); // accent
    expect(cw).toContain("#22c55e"); // profit
    expect(cw).toContain("#ef4444"); // loss
  });
});

// ---------------------------------------------------------------------------
// useTremorTheme
// ---------------------------------------------------------------------------

describe("useTremorTheme", () => {
  it("returns an array", () => {
    const { result } = renderHook(() => useTremorTheme());
    expect(Array.isArray(result.current)).toBe(true);
  });

  it("returns exactly 6 colors", () => {
    const { result } = renderHook(() => useTremorTheme());
    expect(result.current).toHaveLength(6);
  });

  it("all entries are non-empty strings", () => {
    const { result } = renderHook(() => useTremorTheme());
    for (const color of result.current) {
      expect(typeof color).toBe("string");
      expect(color.length).toBeGreaterThan(0);
    }
  });

  it("first entry is the accent color", () => {
    const { result } = renderHook(() => useTremorTheme());
    expect(result.current[0]).toBe("#6366f1");
  });

  it("second entry is the profit (green) color", () => {
    const { result } = renderHook(() => useTremorTheme());
    expect(result.current[1]).toBe("#22c55e");
  });

  it("third entry is the loss (red) color", () => {
    const { result } = renderHook(() => useTremorTheme());
    expect(result.current[2]).toBe("#ef4444");
  });
});

// ---------------------------------------------------------------------------
// useGlideTheme
// ---------------------------------------------------------------------------

describe("useGlideTheme", () => {
  it("returns a non-empty object", () => {
    const { result } = renderHook(() => useGlideTheme());
    expect(result.current).toBeTruthy();
    expect(Object.keys(result.current).length).toBeGreaterThan(0);
  });

  it("has bgCell and bgHeader", () => {
    const { result } = renderHook(() => useGlideTheme());
    expect(result.current.bgCell).toBeTruthy();
    expect(result.current.bgHeader).toBeTruthy();
  });

  it("has text colors for three tiers", () => {
    const { result } = renderHook(() => useGlideTheme());
    expect(result.current.textDark).toBeTruthy();
    expect(result.current.textMedium).toBeTruthy();
    expect(result.current.textLight).toBeTruthy();
  });

  it("has an accentColor", () => {
    const { result } = renderHook(() => useGlideTheme());
    expect(result.current.accentColor).toBeTruthy();
  });

  it("has a borderColor", () => {
    const { result } = renderHook(() => useGlideTheme());
    expect(result.current.borderColor).toBeTruthy();
  });

  it("has fontFamily containing JetBrains Mono", () => {
    const { result } = renderHook(() => useGlideTheme());
    expect(result.current.fontFamily).toContain("JetBrains Mono");
  });

  it("reads --color-accent from CSS vars", () => {
    const { result } = renderHook(() => useGlideTheme());
    expect(result.current.accentColor).toBe("#6366f1");
  });
});

// ---------------------------------------------------------------------------
// useDockviewTheme
// ---------------------------------------------------------------------------

describe("useDockviewTheme", () => {
  it("returns a non-empty Record<string, string>", () => {
    const { result } = renderHook(() => useDockviewTheme());
    expect(typeof result.current).toBe("object");
    expect(Object.keys(result.current).length).toBeGreaterThan(0);
  });

  it("all keys start with --dv-", () => {
    const { result } = renderHook(() => useDockviewTheme());
    for (const key of Object.keys(result.current)) {
      expect(key.startsWith("--dv-")).toBe(true);
    }
  });

  it("all values are non-empty strings", () => {
    const { result } = renderHook(() => useDockviewTheme());
    for (const value of Object.values(result.current)) {
      expect(typeof value).toBe("string");
      expect(value.length).toBeGreaterThan(0);
    }
  });

  it("has background color override", () => {
    const { result } = renderHook(() => useDockviewTheme());
    expect(result.current["--dv-background-color"]).toBeTruthy();
  });

  it("has drag-over border color using accent", () => {
    const { result } = renderHook(() => useDockviewTheme());
    // Accent is #6366f1 — should appear somewhere in drag-over border
    expect(result.current["--dv-drag-over-border-color"]).toBe("#6366f1");
  });

  it("has separator border", () => {
    const { result } = renderHook(() => useDockviewTheme());
    expect(result.current["--dv-separator-border"]).toBeTruthy();
  });

  it("sets Dockview tab variables used by the bundled light and dark themes", () => {
    const { result } = renderHook(() => useDockviewTheme());

    expect(result.current["--dv-tabs-and-actions-container-background-color"]).toBe("#16161f");
    expect(result.current["--dv-activegroup-visiblepanel-tab-background-color"]).toBe("#16161f");
    expect(result.current["--dv-activegroup-visiblepanel-tab-color"]).toBe("#e4e4e7");
  });
});

// ---------------------------------------------------------------------------
// Utility — type-safe access helper to avoid partial-chain errors in tests
// ---------------------------------------------------------------------------

function theme(result: { current: ReturnType<typeof useLightweightChartTheme> }) {
  return result.current;
}
