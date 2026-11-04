import { act, cleanup, render, renderHook, waitFor } from "@testing-library/react";
import { flushSync } from "react-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import Chart from "@/components/Chart";
import { useThemeStore } from "@/stores/themeStore";
import { useLightweightChartTheme } from "../useChartTheme";

// Only the drawing engine and history transport are inert. The production
// store, CSS writes, hooks, consumer and lightweight runtime adapter all run.
const drawing = vi.hoisted(() => {
  const candle = { applyOptions: vi.fn(), setData: vi.fn() };
  const volume = { applyOptions: vi.fn(), setData: vi.fn() };
  const chart = {
    applyOptions: vi.fn(), remove: vi.fn(),
    priceScale: vi.fn(() => ({ applyOptions: vi.fn() })),
    addSeries: vi.fn((kind: string) => kind === "candle" ? candle : volume),
  };
  return { chart, candle, volume, createChart: vi.fn(() => chart) };
});
vi.mock("lightweight-charts", () => ({
  createChart: drawing.createChart, CandlestickSeries: "candle", HistogramSeries: "volume",
  LineSeries: "line", AreaSeries: "area", createSeriesMarkers: vi.fn(),
}));
const history = vi.hoisted(() => vi.fn(async () => [
  { timestamp: 1, open: 10, high: 12, low: 9, close: 11, volume: 20 },
]));
vi.mock("@/services/api", () => ({ getHistory: history }));

let dark = false;
const listeners = new Set<() => void>();
function switchSystem(next: boolean) {
  act(() => { dark = next; for (const listener of [...listeners]) listener(); });
}
function lastBackground() {
  return drawing.chart.applyOptions.mock.lastCall?.[0].layout.background.color;
}
beforeEach(() => {
  vi.clearAllMocks();
  useThemeStore.getState().setMode("light");
  dark = false;
  listeners.clear();
  vi.spyOn(window, "matchMedia").mockImplementation((query) => ({
    media: query, get matches() { return dark; }, onchange: null,
    addEventListener: (_event: string, listener: () => void) => listeners.add(listener),
    removeEventListener: (_event: string, listener: () => void) => listeners.delete(listener),
    addListener: (listener: () => void) => listeners.add(listener),
    removeListener: (listener: () => void) => listeners.delete(listener),
    dispatchEvent: () => true,
  }) as unknown as MediaQueryList);
  useThemeStore.getState().setTheme("graphite");
  useThemeStore.getState().setMode("system");
});
afterEach(() => {
  cleanup();
  useThemeStore.getState().setMode("light");
  vi.restoreAllMocks();
});

describe("live chart theme bridge", () => {
  it("publishes a system change to real subscribers after writing CSS", () => {
    const palettes: string[] = [];
    const unsubscribe = useThemeStore.subscribe(() => {
      palettes.push(document.documentElement.style.getPropertyValue("--chart-bg"));
    });
    try {
      switchSystem(true);
      expect(useThemeStore.getState().getResolvedMode()).toBe("dark");
      expect(palettes).toEqual(["#0a0a0f"]);
    } finally { unsubscribe(); }
  });

  it("repaints the mounted real chart consumer in both directions without recreation or data reload", async () => {
    const { unmount } = render(<Chart />);
    await waitFor(() => expect(drawing.candle.setData).toHaveBeenCalledTimes(1));
    expect(lastBackground()).toBe("#f5f5f7");
    switchSystem(true);
    expect(document.documentElement.dataset.mode).toBe("dark");
    expect(lastBackground()).toBe("#0a0a0f");
    switchSystem(false);
    expect(document.documentElement.dataset.mode).toBe("light");
    expect(lastBackground()).toBe("#f5f5f7");
    expect(drawing.createChart).toHaveBeenCalledTimes(1);
    expect(drawing.chart.remove).not.toHaveBeenCalled();
    expect(history).toHaveBeenCalledTimes(1);
    expect(drawing.candle.setData).toHaveBeenCalledTimes(1);
    expect(drawing.volume.setData).toHaveBeenCalledTimes(1);
    for (const [options] of drawing.chart.applyOptions.mock.calls) {
      expect(options.timeScale).not.toHaveProperty("barSpacing");
      expect(options.timeScale).not.toHaveProperty("rightOffset");
    }
    unmount();
    expect(drawing.chart.remove).toHaveBeenCalledTimes(1);
  });

  it("notifies mounted real theme hooks only after the canonical CSS palette is ready", () => {
    const { result } = renderHook(useLightweightChartTheme);
    const initial = result.current;
    switchSystem(true);
    expect(result.current).not.toBe(initial);
    expect(result.current.layout?.background).toEqual({ color: "#0a0a0f" });
    expect(result.current.candle.upColor).toBe("#22c55e");
    switchSystem(false);
    expect(result.current.layout?.background).toEqual({ color: "#f5f5f7" });
  });

  it.each(["dark", "light"] as const)("keeps manual %s authoritative, then resumes system following with one listener", (mode) => {
    const { result } = renderHook(useLightweightChartTheme);
    act(() => useThemeStore.getState().setMode(mode));
    const manual = result.current;
    expect(listeners.size).toBe(0);
    expect(manual.layout?.background).toEqual({ color: mode === "dark" ? "#0a0a0f" : "#f5f5f7" });
    switchSystem(true);
    switchSystem(false);
    expect(result.current).toBe(manual);
    act(() => useThemeStore.getState().setMode("system"));
    act(() => useThemeStore.getState().setMode("system"));
    expect(listeners.size).toBe(1);
    switchSystem(true);
    expect(result.current.layout?.background).toEqual({ color: "#0a0a0f" });
  });

  it("stops canvas palette reads after unmount and detaches system following on manual selection", () => {
    const reads = vi.spyOn(window, "getComputedStyle");
    const { unmount } = renderHook(useLightweightChartTheme);
    expect(reads).toHaveBeenCalled();
    unmount();
    reads.mockClear();
    switchSystem(true);
    switchSystem(false);
    expect(reads).not.toHaveBeenCalled();
    expect(listeners.size).toBe(1);
    useThemeStore.getState().setMode("dark");
    expect(listeners.size).toBe(0);
  });

  it("does not memoise old CSS if a subscriber synchronously renders during manual selection", () => {
    const { result, rerender } = renderHook(useLightweightChartTheme);
    const unsubscribe = useThemeStore.subscribe((state, previous) => {
      if (state.activeThemeId !== previous.activeThemeId || state.mode !== previous.mode) {
        flushSync(() => rerender());
      }
    });
    try {
      act(() => useThemeStore.getState().setTheme("midnight"));
      expect(result.current.layout?.background).toEqual({ color: "#f0f7ff" });
      act(() => useThemeStore.getState().setMode("dark"));
      expect(result.current.layout?.background).toEqual({ color: "#060a14" });
      act(() => useThemeStore.getState().setMode("light"));
      expect(result.current.layout?.background).toEqual({ color: "#f0f7ff" });
    } finally { unsubscribe(); }
  });

  it.each([true, false])("resolves a cold system mount with dark=%s and keeps only preferences persisted", (isDark) => {
    dark = isDark;
    useThemeStore.getState().setMode("system");
    const { result } = renderHook(useLightweightChartTheme);
    expect(result.current.layout?.background).toEqual({ color: isDark ? "#0a0a0f" : "#f5f5f7" });
    expect(JSON.parse(localStorage.getItem("flinttrade-theme")!).state).toEqual({
      activeThemeId: "graphite", mode: "system", customThemes: [], glass: true, reduceMotion: false,
    });
  });
});
