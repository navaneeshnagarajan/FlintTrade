import { fireEvent, render, waitFor } from "@testing-library/react";
import type {
  IChartApi,
  ISeriesApi,
  ISeriesMarkersPluginApi,
  Time,
} from "lightweight-charts";
import { useRef, type Dispatch, type MutableRefObject, type SetStateAction } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { lightweightLineRuntime } from "@/lib/lightweightChartRuntime";
import type { Drawing, DrawingPoint, DrawToolType } from "../types";
import { useDrawingTools } from "../useDrawingTools";

const drawingRuntimeMocks = vi.hoisted(() => {
  const lineSeries = {
    applyOptions: vi.fn(),
    setData: vi.fn(),
  };
  return {
    addLineSeries: vi.fn(() => lineSeries),
    lineSeries,
  };
});

const directSeries = {
  applyOptions: vi.fn(),
  setData: vi.fn(),
};

const chart = {
  addSeries: vi.fn(() => directSeries),
  removeSeries: vi.fn(),
  subscribeClick: vi.fn(),
  unsubscribeClick: vi.fn(),
  timeScale: vi.fn(() => ({
    coordinateToTime: vi.fn((_coordinate: number) => 1 as Time),
  })),
};

const candle = {
  coordinateToPrice: vi.fn((_coordinate: number) => 22100),
  createPriceLine: vi.fn(),
  removePriceLine: vi.fn(),
};

const markersPlugin = {
  setMarkers: vi.fn(),
};

vi.mock("lightweight-charts", () => ({
  createSeriesMarkers: vi.fn(),
  LineSeries: Symbol("LineSeries"),
}));

vi.mock("@/lib/lightweightChartRuntime", () => ({
  lightweightLineRuntime: {
    addLineSeries: drawingRuntimeMocks.addLineSeries,
  },
}));

const drawings: Drawing[] = [
  {
    id: "trend-1",
    kind: "trendline",
    p1: { price: 22000, time: 1 as Time },
    p2: { price: 22100, time: 2 as Time },
  },
];

interface DrawingToolsHarnessProps {
  drawMode?: DrawToolType | null;
  drawingsValue?: Drawing[];
  onDrawingCreated?: (drawingId: string) => void;
  selectedDrawingId?: string | null;
  setAwaitingText?: Dispatch<SetStateAction<DrawingPoint | null>>;
  setDrawings?: Dispatch<SetStateAction<Drawing[]>>;
  setPendingPoint?: Dispatch<SetStateAction<DrawingPoint | null>>;
}

function DrawingToolsHarness({
  drawMode = null,
  drawingsValue = drawings,
  onDrawingCreated = vi.fn(),
  selectedDrawingId = "trend-1",
  setAwaitingText = vi.fn() as Dispatch<SetStateAction<DrawingPoint | null>>,
  setDrawings = vi.fn() as Dispatch<SetStateAction<Drawing[]>>,
  setPendingPoint = vi.fn() as Dispatch<SetStateAction<DrawingPoint | null>>,
}: DrawingToolsHarnessProps = {}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef(chart as unknown as IChartApi | null) as MutableRefObject<IChartApi | null>;
  const candleRef = useRef(
    candle as unknown as ISeriesApi<"Candlestick"> | null,
  ) as MutableRefObject<ISeriesApi<"Candlestick"> | null>;
  const markersPluginRef = useRef(
    markersPlugin as unknown as ISeriesMarkersPluginApi<Time> | null,
  ) as MutableRefObject<ISeriesMarkersPluginApi<Time> | null>;

  useDrawingTools({
    candleRef,
    chartRef,
    containerRef,
    drawMode,
    drawings: drawingsValue,
    markersPluginRef,
    onDrawingCreated,
    pendingPoint: null,
    selectedDrawingId,
    setAwaitingText,
    setDrawMode: vi.fn() as Dispatch<SetStateAction<DrawToolType | null>>,
    setDrawings,
    setPendingPoint,
  });

  return <div ref={containerRef} />;
}

describe("useDrawingTools", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    candle.coordinateToPrice.mockImplementation((_coordinate: number) => 22100);
    chart.timeScale.mockImplementation(() => ({
      coordinateToTime: vi.fn((_coordinate: number) => 1 as Time),
    }));
  });

  it("renders line drawings through the shared Flint chart runtime", async () => {
    render(<DrawingToolsHarness />);

    await waitFor(() => {
      expect(lightweightLineRuntime.addLineSeries).toHaveBeenCalledWith(
        chart,
        expect.objectContaining({
          priceLineVisible: false,
          priceScaleId: "right",
        }),
      );
    });

    expect(drawingRuntimeMocks.lineSeries.setData).toHaveBeenCalledWith([
      { time: 1, value: 22000 },
      { time: 2, value: 22100 },
    ]);
    expect(chart.addSeries).not.toHaveBeenCalled();
  });

  it("reuses unchanged drawing series when only selection markers change", async () => {
    const { rerender } = render(<DrawingToolsHarness selectedDrawingId={null} />);

    await waitFor(() => {
      expect(lightweightLineRuntime.addLineSeries).toHaveBeenCalledTimes(1);
    });

    drawingRuntimeMocks.addLineSeries.mockClear();
    drawingRuntimeMocks.lineSeries.setData.mockClear();
    chart.removeSeries.mockClear();
    markersPlugin.setMarkers.mockClear();

    rerender(<DrawingToolsHarness selectedDrawingId="trend-1" />);

    await waitFor(() => {
      expect(markersPlugin.setMarkers).toHaveBeenCalledWith(expect.arrayContaining([
        expect.objectContaining({ price: 22000, text: "1", time: 1 }),
        expect.objectContaining({ price: 22100, text: "2", time: 2 }),
      ]));
    });

    expect(lightweightLineRuntime.addLineSeries).not.toHaveBeenCalled();
    expect(drawingRuntimeMocks.lineSeries.setData).not.toHaveBeenCalled();
    expect(chart.removeSeries).not.toHaveBeenCalled();
  });

  it("renders extended line drawings through extrapolated core line data", async () => {
    render(
      <DrawingToolsHarness
        drawingsValue={[
          {
            id: "extended",
            kind: "extended_line",
            p1: { price: 22000, time: 10 as Time },
            p2: { price: 22100, time: 20 as Time },
          },
        ]}
      />,
    );

    await waitFor(() => {
      expect(lightweightLineRuntime.addLineSeries).toHaveBeenCalledWith(
        chart,
        expect.objectContaining({
          priceLineVisible: false,
          priceScaleId: "right",
        }),
      );
    });

    expect(drawingRuntimeMocks.lineSeries.setData).toHaveBeenCalledWith([
      { time: -240, value: 19500 },
      { time: 270, value: 24600 },
    ]);
  });

  it("renders circle drawings through shared core arc line data", async () => {
    render(
      <DrawingToolsHarness
        drawingsValue={[
          {
            id: "circle",
            kind: "circle",
            p1: { price: 22000, time: 10 as Time },
            p2: { price: 22200, time: 20 as Time },
          },
        ]}
      />,
    );

    await waitFor(() => {
      expect(lightweightLineRuntime.addLineSeries).toHaveBeenCalledTimes(2);
    });

    expect(drawingRuntimeMocks.lineSeries.setData).toHaveBeenNthCalledWith(1, expect.arrayContaining([
      { time: 10, value: 22100 },
      { time: 15, value: 22200 },
      { time: 20, value: 22100 },
    ]));
    expect(drawingRuntimeMocks.lineSeries.setData).toHaveBeenNthCalledWith(2, expect.arrayContaining([
      { time: 10, value: 22100 },
      { time: 15, value: 22000 },
      { time: 20, value: 22100 },
    ]));
  });

  it("renders parallel channel drawings through shared core channel line data", async () => {
    render(
      <DrawingToolsHarness
        drawingsValue={[
          {
            id: "channel",
            kind: "parallel_channel",
            p1: { price: 22000, time: 10 as Time },
            p2: { price: 22100, time: 20 as Time },
            p3: { price: 22200, time: 12 as Time },
          },
        ]}
      />,
    );

    await waitFor(() => {
      expect(lightweightLineRuntime.addLineSeries).toHaveBeenCalledTimes(4);
    });

    expect(drawingRuntimeMocks.lineSeries.setData).toHaveBeenNthCalledWith(1, [
      { time: 10, value: 22000 },
      { time: 20, value: 22100 },
    ]);
    expect(drawingRuntimeMocks.lineSeries.setData).toHaveBeenNthCalledWith(2, [
      { time: 12, value: 22200 },
      { time: 22, value: 22300 },
    ]);
    expect(drawingRuntimeMocks.lineSeries.setData).toHaveBeenNthCalledWith(3, [
      { time: 10, value: 22000 },
      { time: 12, value: 22200 },
    ]);
    expect(drawingRuntimeMocks.lineSeries.setData).toHaveBeenNthCalledWith(4, [
      { time: 20, value: 22100 },
      { time: 22, value: 22300 },
    ]);
  });

  it("renders fib extension drawings through shared core extension price lines", async () => {
    render(
      <DrawingToolsHarness
        drawingsValue={[
          {
            id: "fib-extension",
            kind: "fib_extension",
            p1: { price: 100, time: 1 as Time },
            p2: { price: 200, time: 2 as Time },
            p3: { price: 150, time: 3 as Time },
          },
        ]}
      />,
    );

    await waitFor(() => {
      expect(candle.createPriceLine).toHaveBeenCalledTimes(6);
    });

    expect(candle.createPriceLine).toHaveBeenNthCalledWith(1, expect.objectContaining({
      price: 150,
      title: "Fib Ext 0.0%",
    }));
    expect(candle.createPriceLine).toHaveBeenNthCalledWith(3, expect.objectContaining({
      price: 250,
      title: "Fib Ext 100.0%",
    }));
    expect(candle.createPriceLine).toHaveBeenNthCalledWith(6, expect.objectContaining({
      price: 411.8,
      title: "Fib Ext 261.8%",
    }));
  });

  it("renders long and short position drawings through shared core risk price lines", async () => {
    render(
      <DrawingToolsHarness
        drawingsValue={[
          {
            id: "long-position",
            kind: "long_position",
            p1: { price: 100, time: 1 as Time },
            p2: { price: 130, time: 2 as Time },
            p3: { price: 90, time: 3 as Time },
          },
          {
            id: "short-position",
            kind: "short_position",
            p1: { price: 100, time: 1 as Time },
            p2: { price: 70, time: 2 as Time },
            p3: { price: 110, time: 3 as Time },
          },
        ]}
      />,
    );

    await waitFor(() => {
      expect(candle.createPriceLine).toHaveBeenCalledTimes(6);
    });

    expect(candle.createPriceLine).toHaveBeenNthCalledWith(1, expect.objectContaining({
      price: 100,
      title: "Long Entry",
    }));
    expect(candle.createPriceLine).toHaveBeenNthCalledWith(2, expect.objectContaining({
      price: 130,
      title: "Long Target",
    }));
    expect(candle.createPriceLine).toHaveBeenNthCalledWith(3, expect.objectContaining({
      price: 90,
      title: "Long Stop",
    }));
    expect(candle.createPriceLine).toHaveBeenNthCalledWith(4, expect.objectContaining({
      price: 100,
      title: "Short Entry",
    }));
    expect(candle.createPriceLine).toHaveBeenNthCalledWith(5, expect.objectContaining({
      price: 70,
      title: "Short Target",
    }));
    expect(candle.createPriceLine).toHaveBeenNthCalledWith(6, expect.objectContaining({
      price: 110,
      title: "Short Stop",
    }));
  });

  it("renders Elliott pattern drawings through shared core wave lines and labels", async () => {
    render(
      <DrawingToolsHarness
        drawingsValue={[
          {
            id: "impulse",
            kind: "elliott_impulse",
            points: [
              { price: 100, time: 1 as Time },
              { price: 120, time: 2 as Time },
              { price: 110, time: 3 as Time },
              { price: 140, time: 4 as Time },
              { price: 128, time: 5 as Time },
              { price: 155, time: 6 as Time },
            ],
          },
        ]}
      />,
    );

    await waitFor(() => {
      expect(lightweightLineRuntime.addLineSeries).toHaveBeenCalledTimes(1);
    });

    expect(drawingRuntimeMocks.lineSeries.setData).toHaveBeenCalledWith([
      { time: 1, value: 100 },
      { time: 2, value: 120 },
      { time: 3, value: 110 },
      { time: 4, value: 140 },
      { time: 5, value: 128 },
      { time: 6, value: 155 },
    ]);
    expect(markersPlugin.setMarkers).toHaveBeenCalledWith(expect.arrayContaining([
      expect.objectContaining({ text: "0", time: 1, price: 100 }),
      expect.objectContaining({ text: "5", time: 6, price: 155 }),
    ]));
  });

  it("renders brush drawings through shared core freehand line data", async () => {
    render(
      <DrawingToolsHarness
        drawingsValue={[
          {
            id: "brush",
            kind: "brush",
            points: [
              { price: 100, time: 1 as Time },
              { price: 105, time: 2 as Time },
              { price: 102, time: 3 as Time },
            ],
          },
        ]}
      />,
    );

    await waitFor(() => {
      expect(lightweightLineRuntime.addLineSeries).toHaveBeenCalledTimes(1);
    });

    expect(drawingRuntimeMocks.lineSeries.setData).toHaveBeenCalledWith([
      { time: 1, value: 100 },
      { time: 2, value: 105 },
      { time: 3, value: 102 },
    ]);
  });

  it("creates brush drawings from pointer drag points", async () => {
    const setDrawings = vi.fn();
    candle.coordinateToPrice.mockImplementation((coordinate: number) => 1000 - coordinate);
    chart.timeScale.mockImplementation(() => ({
      coordinateToTime: vi.fn((coordinate: number) => coordinate as Time),
    }));

    const { container } = render(
      <DrawingToolsHarness
        drawMode="brush"
        setDrawings={setDrawings as Dispatch<SetStateAction<Drawing[]>>}
      />,
    );
    const workspace = container.firstElementChild as HTMLDivElement;
    Object.defineProperty(workspace, "getBoundingClientRect", {
      value: () => ({ left: 0, top: 0, width: 500, height: 300, right: 500, bottom: 300 }),
    });
    workspace.setPointerCapture = vi.fn();
    workspace.releasePointerCapture = vi.fn();

    fireEvent.pointerDown(workspace, { button: 0, buttons: 1, clientX: 10, clientY: 20, pointerId: 1 });
    fireEvent.pointerMove(window, { buttons: 1, clientX: 20, clientY: 30, pointerId: 1 });
    fireEvent.pointerMove(window, { buttons: 1, clientX: 30, clientY: 25, pointerId: 1 });
    fireEvent.pointerUp(window, { pointerId: 1 });

    await waitFor(() => {
      expect(setDrawings).toHaveBeenCalledWith(expect.any(Function));
    });
    const updater = setDrawings.mock.calls[0]?.[0] as (prev: Drawing[]) => Drawing[];
    const next = updater([]);

    expect(next[0]).toMatchObject({
      kind: "brush",
      points: [
        { time: 10, price: 980 },
        { time: 20, price: 970 },
        { time: 30, price: 975 },
      ],
    });
  });

  it("renders price label drawings through shared core marker specs", async () => {
    render(
      <DrawingToolsHarness
        drawingsValue={[
          { kind: "price_label", id: "price", point: { time: 4 as Time, price: 22440 } },
        ]}
      />,
    );

    await waitFor(() => {
      expect(markersPlugin.setMarkers).toHaveBeenCalledWith([
        expect.objectContaining({
          time: 4,
          price: 22440,
          text: "22,440.00",
        }),
      ]);
    });
  });

  it("renders callout drawings through shared core marker specs", async () => {
    render(
      <DrawingToolsHarness
        drawingsValue={[
          { kind: "callout", id: "callout", point: { time: 5 as Time, price: 22500 }, label: "Watch" },
        ]}
      />,
    );

    await waitFor(() => {
      expect(markersPlugin.setMarkers).toHaveBeenCalledWith([
        expect.objectContaining({
          time: 5,
          price: 22500,
          text: "Watch",
        }),
      ]);
    });
  });

  it("applies the shared core drawing draft result on chart clicks", async () => {
    const setDrawings = vi.fn();
    const onDrawingCreated = vi.fn();
    render(
      <DrawingToolsHarness
        drawMode="hline"
        onDrawingCreated={onDrawingCreated}
        setDrawings={setDrawings as Dispatch<SetStateAction<Drawing[]>>}
      />,
    );

    await waitFor(() => {
      expect(chart.subscribeClick).toHaveBeenCalled();
    });

    const clickHandler = chart.subscribeClick.mock.calls.at(-1)?.[0] as (
      param: { point: { x: number; y: number }; time: Time },
    ) => void;
    clickHandler({ point: { x: 12, y: 24 }, time: 1 as Time });

    expect(setDrawings).toHaveBeenCalledWith(expect.any(Function));
    const updater = setDrawings.mock.calls[0]?.[0] as (prev: Drawing[]) => Drawing[];
    const next = updater([]);

    expect(next[0]).toMatchObject({ kind: "hline", price: 22100 });
    expect(typeof next[0]?.id).toBe("string");
    expect(onDrawingCreated).toHaveBeenCalledWith(next[0]?.id);
  });

  it("keeps the pending point current across rapid two-click drawing events", async () => {
    const setDrawings = vi.fn();
    const setPendingPoint = vi.fn();
    render(
      <DrawingToolsHarness
        drawMode="trendline"
        setDrawings={setDrawings as Dispatch<SetStateAction<Drawing[]>>}
        setPendingPoint={setPendingPoint as Dispatch<SetStateAction<DrawingPoint | null>>}
      />,
    );

    await waitFor(() => {
      expect(chart.subscribeClick).toHaveBeenCalled();
    });

    const clickHandler = chart.subscribeClick.mock.calls.at(-1)?.[0] as (
      param: { point: { x: number; y: number }; time: Time },
    ) => void;
    clickHandler({ point: { x: 12, y: 24 }, time: 1 as Time });
    clickHandler({ point: { x: 24, y: 36 }, time: 2 as Time });

    expect(setPendingPoint).toHaveBeenCalledWith({ time: 1, price: 22100 });
    expect(setDrawings).toHaveBeenCalledWith(expect.any(Function));
    const updater = setDrawings.mock.calls[0]?.[0] as (prev: Drawing[]) => Drawing[];
    const next = updater([]);

    expect(next[0]).toMatchObject({
      kind: "trendline",
      p1: { time: 1, price: 22100 },
      p2: { time: 2, price: 22100 },
    });
  });

  it("creates two-click drawings from native chart pointer events", async () => {
    const setDrawings = vi.fn();
    const setPendingPoint = vi.fn();
    const { container } = render(
      <DrawingToolsHarness
        drawMode="trendline"
        setDrawings={setDrawings as Dispatch<SetStateAction<Drawing[]>>}
        setPendingPoint={setPendingPoint as Dispatch<SetStateAction<DrawingPoint | null>>}
      />,
    );
    const chartContainer = container.firstElementChild as HTMLDivElement;

    await waitFor(() => {
      expect(chart.subscribeClick).toHaveBeenCalled();
    });

    chartContainer.dispatchEvent(new MouseEvent("pointerdown", {
      bubbles: true,
      button: 0,
      buttons: 1,
      clientX: 12,
      clientY: 24,
    }));
    chartContainer.dispatchEvent(new MouseEvent("pointerdown", {
      bubbles: true,
      button: 0,
      buttons: 1,
      clientX: 24,
      clientY: 36,
    }));

    expect(setPendingPoint).toHaveBeenCalledWith({ time: 1, price: 22100 });
    expect(setDrawings).toHaveBeenCalledWith(expect.any(Function));
  });

  it("deletes an unlocked hit drawing when the eraser tool is active", async () => {
    const setDrawings = vi.fn();
    const { container } = render(
      <DrawingToolsHarness
        drawMode="eraser"
        drawingsValue={[{ kind: "hline", id: "support", price: 22100 }]}
        setDrawings={setDrawings as Dispatch<SetStateAction<Drawing[]>>}
      />,
    );
    const chartContainer = container.firstElementChild as HTMLDivElement;

    chartContainer.dispatchEvent(new MouseEvent("pointerdown", {
      bubbles: true,
      button: 0,
      buttons: 1,
      clientX: 12,
      clientY: 24,
    }));

    expect(setDrawings).toHaveBeenCalledWith(expect.any(Function));
    const updater = setDrawings.mock.calls[0]?.[0] as (prev: Drawing[]) => Drawing[];

    expect(updater([{ kind: "hline", id: "support", price: 22100 }])).toEqual([]);
  });

  it("leaves locked drawings intact when the eraser tool hits them", async () => {
    const setDrawings = vi.fn();
    const lockedDrawing: Drawing = { kind: "hline", id: "support", price: 22100, locked: true };
    const { container } = render(
      <DrawingToolsHarness
        drawMode="eraser"
        drawingsValue={[lockedDrawing]}
        setDrawings={setDrawings as Dispatch<SetStateAction<Drawing[]>>}
      />,
    );
    const chartContainer = container.firstElementChild as HTMLDivElement;

    chartContainer.dispatchEvent(new MouseEvent("pointerdown", {
      bubbles: true,
      button: 0,
      buttons: 1,
      clientX: 12,
      clientY: 24,
    }));

    expect(setDrawings).not.toHaveBeenCalled();
  });
});
