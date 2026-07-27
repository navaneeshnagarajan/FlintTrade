/**
 * chartThemeHooks.test.ts
 *
 * Tests for the chart-theme hooks:
 *   - useLightweightChartTheme
 *   - usePlotlyTheme
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
import { useGlideTheme } from "../useGlideTheme";
import { useFlexLayoutTheme } from "../useFlexLayoutTheme";

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

  it("uses the core chart interaction contract", () => {
    const { result } = renderHook(() => useLightweightChartTheme());
    expect(theme(result).handleScale).toMatchObject({
      mouseWheel: true,
      pinch: true,
      axisPressedMouseMove: { time: true, price: true },
      axisDoubleClickReset: { time: true, price: true },
    });
    expect(theme(result).handleScroll).toMatchObject({
      mouseWheel: true,
      pressedMouseMove: true,
      horzTouchDrag: true,
      vertTouchDrag: false,
    });
    expect(theme(result).kineticScroll).toMatchObject({ touch: true, mouse: true });
  });

  it("uses labelled crosshair and stable scale defaults", () => {
    const { result } = renderHook(() => useLightweightChartTheme());
    expect(theme(result).crosshair?.vertLine?.labelVisible).toBe(true);
    expect(theme(result).crosshair?.horzLine?.labelVisible).toBe(true);
    expect(theme(result).rightPriceScale?.minimumWidth).toBeGreaterThan(0);
    expect(theme(result).rightPriceScale?.ticksVisible).toBe(true);
    expect(theme(result).timeScale?.rightOffset).toBeGreaterThan(0);
    expect(theme(result).timeScale?.lockVisibleTimeRangeOnResize).toBe(true);
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
// useFlexLayoutTheme
// ---------------------------------------------------------------------------

describe("useFlexLayoutTheme", () => {
  it("returns a non-empty Record<string, string>", () => {
    const { result } = renderHook(() => useFlexLayoutTheme());
    expect(typeof result.current).toBe("object");
    expect(Object.keys(result.current).length).toBeGreaterThan(0);
  });

  it("all keys are CSS custom properties", () => {
    const { result } = renderHook(() => useFlexLayoutTheme());
    for (const key of Object.keys(result.current)) {
      expect(key.startsWith("--")).toBe(true);
    }
  });

  it("all values are non-empty strings", () => {
    const { result } = renderHook(() => useFlexLayoutTheme());
    for (const value of Object.values(result.current)) {
      expect(typeof value).toBe("string");
      expect(value.length).toBeGreaterThan(0);
    }
  });

  it("has background color override", () => {
    const { result } = renderHook(() => useFlexLayoutTheme());
    expect(result.current["--color-background"]).toBeTruthy();
  });

  it("has drag affordance colour using accent", () => {
    const { result } = renderHook(() => useFlexLayoutTheme());
    // Accent is #6366f1 — the drag edge/outline colour
    expect(result.current["--color-drag1"]).toBe("#6366f1");
  });

  it("has splitter colours", () => {
    const { result } = renderHook(() => useFlexLayoutTheme());
    expect(result.current["--color-splitter"]).toBeTruthy();
    expect(result.current["--color-splitter-hover"]).toBe("#6366f1");
  });

  it("sets FlexLayout tab variables used by the bundled light and dark themes", () => {
    const { result } = renderHook(() => useFlexLayoutTheme());

    expect(result.current["--color-tabset-background"]).toBe("#16161f");
    expect(result.current["--color-tab-selected"]).toBe("#e4e4e7");
    expect(result.current["--color-tab-unselected"]).toBe("#8b8b95");
  });
});

// ---------------------------------------------------------------------------
// Utility — type-safe access helper to avoid partial-chain errors in tests
// ---------------------------------------------------------------------------

function theme(result: { current: ReturnType<typeof useLightweightChartTheme> }) {
  return result.current;
}
