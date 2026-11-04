import { act, cleanup, fireEvent, render, renderHook, screen } from "@testing-library/react";
import { Activity, useState } from "react";
import type { IChartApi, ISeriesApi } from "lightweight-charts";
import type { LegendState } from "../ChartLegend";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Button } from "@/components/ui/button";
import { useChartInit } from "../useChartInit";
import { useDrawingTools } from "../useDrawingTools";
import type { Drawing, DrawingPoint, DrawToolType } from "../types";

// Only the native drawing boundary is doubled. Both production hooks, their
// actual mount/cleanup order, shared chart adapter and drawing render plan run.
// Lightweight Charts cancels pending paint in remove(), but removePriceLine()
// can invalidate it again afterwards. The browser async stack pins that path.
const native = vi.hoisted(() => {
  function createChart() {
    let removed = false;
    let pending: (() => void) | null = null;
    const operations: string[] = [];
    const clicks = new Set<(...args: unknown[]) => void>();
    const crosshairs = new Set<(...args: unknown[]) => void>();
    const priceLines = new Set<object>();
    const series: object[] = [];
    function invalidate() {
      pending = () => {
        pending = null;
        if (removed) throw new Error("Object is disposed");
      };
    }
    const chart = {
      operations, clicks, crosshairs, priceLines, series,
      get removed() { return removed; },
      get pending() { return pending; },
      paint() { pending?.(); },
      applyOptions: vi.fn(invalidate),
      priceScale: () => ({ applyOptions: vi.fn() }),
      timeScale: () => ({ coordinateToTime: () => 1 }),
      subscribeCrosshairMove: (listener: (...args: unknown[]) => void) => crosshairs.add(listener),
      subscribeClick: (listener: (...args: unknown[]) => void) => clicks.add(listener),
      unsubscribeClick: (listener: (...args: unknown[]) => void) => clicks.delete(listener),
      addSeries: vi.fn(() => {
        const item = {
          applyOptions: vi.fn(invalidate), setData: vi.fn(invalidate),
          coordinateToPrice: (value: number) => value + 100,
          createPriceLine: vi.fn(() => {
            operations.push("createPriceLine");
            const line = {}; priceLines.add(line); invalidate(); return line;
          }),
          removePriceLine: vi.fn((line: object) => {
            operations.push(removed ? "removePriceLine:retired" : "removePriceLine:live");
            priceLines.delete(line); invalidate();
          }),
        };
        series.push(item); return item;
      }),
      removeSeries: vi.fn((item: object) => {
        operations.push(removed ? "removeSeries:retired" : "removeSeries:live");
        const index = series.indexOf(item);
        if (index < 0) throw new Error("Foreign series");
        series.splice(index, 1); invalidate();
      }),
      remove: vi.fn(() => {
        operations.push("remove"); removed = true; pending = null;
        priceLines.clear(); series.length = 0; clicks.clear(); crosshairs.clear();
      }),
    };
    return chart;
  }
  const charts: ReturnType<typeof createChart>[] = [];
  return {
    charts,
    createChart: vi.fn(() => { const chart = createChart(); charts.push(chart); return chart; }),
  };
});
vi.mock("lightweight-charts", () => ({
  createChart: native.createChart,
  CandlestickSeries: "candle", HistogramSeries: "volume", LineSeries: "line", AreaSeries: "area",
  createSeriesMarkers: () => ({ setMarkers: vi.fn() }),
}));

function ChartLifecycle({ id = "chart" }: { id?: string }) {
  const [, setLegend] = useState<LegendState | null>(null);
  const refs = useChartInit(setLegend);
  const [drawMode, setDrawMode] = useState<DrawToolType | null>(null);
  const [drawings, setDrawings] = useState<Drawing[]>([]);
  const [pendingPoint, setPendingPoint] = useState<DrawingPoint | null>(null);
  const [, setAwaitingText] = useState<DrawingPoint | null>(null);
  const { toggleDrawMode, clearAllDrawings } = useDrawingTools({
    ...refs, drawMode, setDrawMode, drawings, setDrawings,
    pendingPoint, setPendingPoint, setAwaitingText,
  });
  return <section aria-label={id}>
    <Button onClick={() => toggleDrawMode("hline")}>Draw {id}</Button>
    <Button onClick={clearAllDrawings}>Clear {id}</Button>
    <output aria-label={`${id} drawings`}>{drawings.length}</output>
    <div data-testid={id} ref={refs.containerRef} />
  </section>;
}
function draw(id = "chart") {
  fireEvent.click(screen.getByRole("button", { name: `Draw ${id}` }));
  fireEvent.pointerDown(screen.getByTestId(id), { button: 0, clientX: 20, clientY: 20 });
  expect(screen.getByLabelText(`${id} drawings`)).toHaveTextContent("1");
}
beforeEach(() => { native.charts.length = 0; vi.clearAllMocks(); });
afterEach(() => {
  try { cleanup(); } finally { vi.restoreAllMocks(); }
});

describe("mounted chart drawing lifecycle", () => {
  it("cancels an already queued native paint when an undrawn chart retires", () => {
    const { unmount } = render(<ChartLifecycle />);
    const chart = native.charts[0];
    chart.applyOptions();
    const held = chart.pending;
    expect(held).not.toBeNull();
    unmount();
    expect(chart.pending).toBeNull();
    expect(() => chart.paint()).not.toThrow();
    // A callback forced past cancellation must still expose a retired canvas;
    // the native boundary double must not silently forgive use after remove.
    expect(() => held?.()).toThrow("Object is disposed");
    expect(chart.operations).toEqual(["remove"]);
  });

  it("can clear the same drawing while its chart is live before removing the chart", () => {
    const { unmount } = render(<ChartLifecycle />);
    draw();
    const chart = native.charts[0];
    fireEvent.click(screen.getByRole("button", { name: "Clear chart" }));
    expect(chart.operations).toEqual(["createPriceLine", "removePriceLine:live"]);
    expect(chart.priceLines.size).toBe(0);
    unmount();
    expect(() => chart.paint()).not.toThrow();
    expect(chart.operations.at(-1)).toBe("remove");
  });

  it("retires one drawn instance without touching another chart's drawings or paint", () => {
    const { rerender, unmount } = render(<><ChartLifecycle key="a" id="a" /><ChartLifecycle key="b" id="b" /></>);
    draw("a"); draw("b");
    const [first, second] = native.charts;
    first.paint(); second.paint();
    rerender(<ChartLifecycle key="b" id="b" />);
    expect(second.remove).not.toHaveBeenCalled();
    expect(second.priceLines.size).toBe(1);
    expect(second.pending).toBeNull();
    expect(screen.getByLabelText("b drawings")).toHaveTextContent("1");
    expect(() => first.paint()).not.toThrow();
    unmount();
    expect(() => second.paint()).not.toThrow();
  });

  it("releases drawings and listeners before a still-live external chart owner removes its canvas", () => {
    const chart = native.createChart();
    const candle = chart.addSeries();
    const container = document.createElement("div");
    const remove = vi.spyOn(container, "removeEventListener");
    const add = vi.spyOn(container, "addEventListener");
    const addWindow = vi.spyOn(window, "addEventListener");
    const removeWindow = vi.spyOn(window, "removeEventListener");
    const { unmount } = renderHook(() => useDrawingTools({
      containerRef: { current: container },
      chartRef: { current: chart as unknown as IChartApi },
      candleRef: { current: candle as unknown as ISeriesApi<"Candlestick"> },
      markersPluginRef: { current: null },
      drawMode: null, setDrawMode: vi.fn(),
      drawings: [{ id: "line", kind: "hline", price: 120 }],
      setDrawings: vi.fn(), pendingPoint: null, setPendingPoint: vi.fn(), setAwaitingText: vi.fn(),
    }));
    expect(chart.priceLines.size).toBe(1);
    unmount();
    expect(chart.operations).toEqual(["createPriceLine", "removePriceLine:live"]);
    expect(chart.priceLines.size).toBe(0);
    expect(chart.clicks.size).toBe(0);
    for (const args of add.mock.calls) expect(remove).toHaveBeenCalledWith(...args);
    for (const args of addWindow.mock.calls.filter(([type]) => type.startsWith("pointer"))) {
      expect(removeWindow).toHaveBeenCalledWith(...args);
    }
    chart.remove();
    expect(() => chart.paint()).not.toThrow();
    vi.restoreAllMocks();
  });

  it("recreates drawings on Activity return without reusing retired native resources", async () => {
    const view = (mode: "visible" | "hidden") => <Activity mode={mode}><ChartLifecycle /></Activity>;
    const { rerender, unmount } = render(view("visible"));
    draw();
    const first = native.charts[0];
    first.paint();
    rerender(view("hidden"));
    await act(async () => {});
    expect(first.remove).toHaveBeenCalledTimes(1);
    expect(first.pending).toBeNull();
    expect(() => first.paint()).not.toThrow();
    rerender(view("visible"));
    await act(async () => {});
    expect(native.charts).toHaveLength(2);
    const second = native.charts[1];
    expect(second).not.toBe(first);
    expect(screen.getByLabelText("chart drawings")).toHaveTextContent("1");
    expect(second.priceLines.size).toBe(1);
    expect(() => second.paint()).not.toThrow();
    unmount();
    expect(() => second.paint()).not.toThrow();
    expect(first.operations).not.toContain("removePriceLine:retired");
    expect(second.operations).not.toContain("removePriceLine:retired");
  });

  it("does not schedule a disposed canvas paint when a drawn chart is removed", () => {
    const { unmount } = render(<ChartLifecycle />);
    draw();
    const chart = native.charts[0];
    expect(chart.priceLines.size).toBe(1);
    chart.paint(); // No pre-existing paint is required for the failure.
    expect(chart.pending).toBeNull();
    unmount();
    expect(() => chart.paint()).not.toThrow();
    expect(chart.operations).not.toContain("removePriceLine:retired");
    expect(chart.remove).toHaveBeenCalledTimes(1);
    expect(chart.clicks.size).toBe(0);
    expect(chart.crosshairs.size).toBe(0);
  });
});
