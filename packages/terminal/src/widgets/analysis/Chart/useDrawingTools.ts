// Drawing tools hook.
// Manages the click-to-draw state machine (one-click and two-click tools)
// and the effect that renders all current drawings onto the chart.

import { useEffect, useRef, useCallback } from "react";
import { LineSeries, createSeriesMarkers } from "lightweight-charts";
import type {
  IChartApi,
  ISeriesApi,
  ISeriesMarkersPluginApi,
  MouseEventParams,
  LineData,
  SeriesMarker,
  Time,
} from "lightweight-charts";
import type {
  DrawToolType,
  Drawing,
  DrawingPoint,
  DrawingSeriesMap,
  HlineRef,
} from "./types";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const FIB_LEVELS = [0, 0.236, 0.382, 0.5, 0.618, 0.786, 1] as const;
const FIB_COLORS: Record<number, string> = {
  0: "#ef4444",
  0.236: "#f97316",
  0.382: "#eab308",
  0.5: "#22c55e",
  0.618: "#3b82f6",
  0.786: "#a855f7",
  1: "#ef4444",
};

function uid(): string {
  return Math.random().toString(36).slice(2, 10);
}

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

interface UseDrawingToolsOptions {
  chartRef: React.MutableRefObject<IChartApi | null>;
  candleRef: React.MutableRefObject<ISeriesApi<"Candlestick"> | null>;
  markersPluginRef: React.MutableRefObject<ISeriesMarkersPluginApi<Time> | null>;
  drawMode: DrawToolType | null;
  setDrawMode: React.Dispatch<React.SetStateAction<DrawToolType | null>>;
  drawings: Drawing[];
  setDrawings: React.Dispatch<React.SetStateAction<Drawing[]>>;
  pendingPoint: DrawingPoint | null;
  setPendingPoint: React.Dispatch<React.SetStateAction<DrawingPoint | null>>;
  setAwaitingText: React.Dispatch<React.SetStateAction<DrawingPoint | null>>;
}

export function useDrawingTools({
  chartRef,
  candleRef,
  markersPluginRef,
  drawMode,
  setDrawMode,
  drawings,
  setDrawings,
  pendingPoint,
  setPendingPoint,
  setAwaitingText,
}: UseDrawingToolsOptions) {
  // Refs so click handler closures always see the latest values
  const drawModeRef = useRef<DrawToolType | null>(drawMode);
  const pendingPointRef = useRef<DrawingPoint | null>(pendingPoint);
  const clickHandlerRef = useRef<((param: MouseEventParams) => void) | null>(null);
  const drawingSeriesRef = useRef<DrawingSeriesMap>(new Map());
  const hlineSeriesRef = useRef<HlineRef[]>([]);
  const textMarkersRef = useRef<SeriesMarker<Time>[]>([]);

  useEffect(() => { drawModeRef.current = drawMode; }, [drawMode]);
  useEffect(() => { pendingPointRef.current = pendingPoint; }, [pendingPoint]);

  // --- Subscribe / re-subscribe chart click handler whenever drawMode changes ---
  useEffect(() => {
    const chart = chartRef.current;
    const candle = candleRef.current;
    if (!chart || !candle) return;

    if (clickHandlerRef.current) {
      chart.unsubscribeClick(clickHandlerRef.current);
    }

    const handler = (param: MouseEventParams) => {
      const mode = drawModeRef.current;
      if (!param || !param.point || !mode) return;
      const price = candle.coordinateToPrice(param.point.y);
      if (price == null) return;
      const time = param.time as Time | undefined;
      if (!time) return;

      const point: DrawingPoint = { time, price };

      if (mode === "hline") {
        setDrawings((prev) => [...prev, { kind: "hline", id: uid(), price }]);
        return;
      }

      if (mode === "vline") {
        setDrawings((prev) => [...prev, { kind: "vline", id: uid(), time }]);
        return;
      }

      if (mode === "text") {
        setAwaitingText(point);
        return;
      }

      // Two-click tools: trendline, ray, fib, rect
      const pending = pendingPointRef.current;
      if (!pending) {
        setPendingPoint(point);
        return;
      }

      const id = uid();
      if (mode === "trendline") {
        setDrawings((prev) => [...prev, { kind: "trendline", id, p1: pending, p2: point }]);
      } else if (mode === "ray") {
        setDrawings((prev) => [...prev, { kind: "ray", id, p1: pending, p2: point }]);
      } else if (mode === "fib") {
        setDrawings((prev) => [...prev, { kind: "fib", id, p1: pending, p2: point }]);
      } else if (mode === "rect") {
        setDrawings((prev) => [...prev, { kind: "rect", id, p1: pending, p2: point }]);
      }
      setPendingPoint(null);
    };

    clickHandlerRef.current = handler;
    chart.subscribeClick(handler);

    return () => {
      chart.unsubscribeClick(handler);
      clickHandlerRef.current = null;
    };
  // drawMode is intentionally the only dep — the handler body reads live refs
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [drawMode]);

  // --- Re-render all drawings whenever the drawings array changes ---
  useEffect(() => {
    const chart = chartRef.current;
    const candle = candleRef.current;
    if (!chart || !candle) return;

    const dsMap = drawingSeriesRef.current;

    // Clean up all previous drawing series
    for (const seriesList of dsMap.values()) {
      for (const s of seriesList) {
        try { chart.removeSeries(s); } catch { /* ignore */ }
      }
    }
    dsMap.clear();

    // Clean up old price lines from hlines and fib/rect
    for (const ref of hlineSeriesRef.current) {
      try { ref._series.removePriceLine(ref._priceLine); } catch { /* ignore */ }
    }
    hlineSeriesRef.current = [];

    const markers: SeriesMarker<Time>[] = [];
    textMarkersRef.current = [];

    for (const d of drawings) {
      if (d.kind === "hline") {
        try {
          const pl = candle.createPriceLine({
            price: d.price,
            color: "#eab308",
            lineWidth: 1,
            lineStyle: 2,
            axisLabelVisible: true,
            title: "",
          });
          hlineSeriesRef.current.push({ _priceLine: pl, _series: candle });
        } catch { /* ignore */ }

      } else if (d.kind === "vline") {
        // lightweight-charts v5 has no native vertical line;
        // approximate with a square marker at the target time.
        const marker: SeriesMarker<Time> = {
          time: d.time,
          position: "inBar",
          color: "#64748b",
          shape: "square",
          size: 0.5,
          text: "|",
        };
        markers.push(marker);

      } else if (d.kind === "trendline" || d.kind === "ray") {
        try {
          const color = d.kind === "ray" ? "#f97316" : "#3b82f6";
          const s = chart.addSeries(LineSeries, {
            color,
            lineWidth: 1,
            priceScaleId: "right",
            lastValueVisible: false,
            priceLineVisible: false,
          });
          const data: LineData[] = [
            { time: d.p1.time, value: d.p1.price },
            { time: d.p2.time, value: d.p2.price },
          ];
          s.setData(data);
          dsMap.set(d.id, [s]);
        } catch { /* ignore */ }

      } else if (d.kind === "fib") {
        const hiPrice = Math.max(d.p1.price, d.p2.price);
        const loPrice = Math.min(d.p1.price, d.p2.price);
        const range = hiPrice - loPrice;
        for (const level of FIB_LEVELS) {
          const price = hiPrice - range * level;
          const color = FIB_COLORS[level] ?? "#94a3b8";
          try {
            const pl = candle.createPriceLine({
              price,
              color,
              lineWidth: 1,
              lineStyle: 2,
              axisLabelVisible: true,
              title: `Fib ${(level * 100).toFixed(1)}%`,
            });
            hlineSeriesRef.current.push({ _priceLine: pl, _series: candle });
          } catch { /* ignore */ }
        }

      } else if (d.kind === "rect") {
        const topPrice = Math.max(d.p1.price, d.p2.price);
        const botPrice = Math.min(d.p1.price, d.p2.price);
        for (const [price, title] of [
          [topPrice, "Rect Top"],
          [botPrice, "Rect Bot"],
        ] as [number, string][]) {
          try {
            const pl = candle.createPriceLine({
              price,
              color: "#8b5cf6",
              lineWidth: 1,
              lineStyle: 1,
              axisLabelVisible: true,
              title,
            });
            hlineSeriesRef.current.push({ _priceLine: pl, _series: candle });
          } catch { /* ignore */ }
        }

      } else if (d.kind === "text") {
        const marker: SeriesMarker<Time> = {
          time: d.point.time,
          position: "atPriceMiddle",
          color: "#facc15",
          shape: "circle",
          size: 1,
          price: d.point.price,
          text: d.label,
        };
        markers.push(marker);
      }
    }

    if (markersPluginRef.current) {
      try {
        markersPluginRef.current.setMarkers(markers);
        textMarkersRef.current = markers;
      } catch { /* ignore */ }
    }

    return () => {
      for (const seriesList of dsMap.values()) {
        for (const s of seriesList) {
          try { chart.removeSeries(s); } catch { /* ignore */ }
        }
      }
      dsMap.clear();
      for (const ref of hlineSeriesRef.current) {
        try { ref._series.removePriceLine(ref._priceLine); } catch { /* gone */ }
      }
      hlineSeriesRef.current = [];
    };
  }, [drawings, chartRef, candleRef, markersPluginRef]);

  // --- Convenience actions returned to the caller ---
  const toggleDrawMode = useCallback((mode: DrawToolType) => {
    setDrawMode((prev) => {
      if (prev === mode) {
        setPendingPoint(null);
        return null;
      }
      setPendingPoint(null);
      return mode;
    });
  }, [setDrawMode, setPendingPoint]);

  const clearAllDrawings = useCallback(() => {
    setDrawings([]);
    setPendingPoint(null);
  }, [setDrawings, setPendingPoint]);

  const undoLastDrawing = useCallback(() => {
    setDrawings((prev) => prev.slice(0, -1));
  }, [setDrawings]);

  // Expose the markers plugin ref so the parent can re-use it for
  // createSeriesMarkers initialisation (already done in useChartInit).
  // Also expose the internal series refs for cleanup on symbol change.
  return {
    drawingSeriesRef,
    hlineSeriesRef,
    toggleDrawMode,
    clearAllDrawings,
    undoLastDrawing,
  };
}

export { createSeriesMarkers };
