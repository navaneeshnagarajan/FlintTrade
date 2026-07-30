// Drawing tools hook.
// Manages the click-to-draw state machine (one-click and two-click tools)
// and the effect that renders all current drawings onto the chart.

import { useEffect, useRef, useCallback } from "react";
import {
  advanceFlintChartDrawingDraft,
  createFlintChartBrushDrawing,
  createFlintChartDrawingRenderPlan,
  createFlintChartDrawingRenderPlanDiff,
  findFlintChartDrawingHit,
  findFlintChartDrawingHandleHit,
  getFlintChartTimeDelta,
  removeFlintChartDrawingById,
} from "@flinttrade/design-system";
import { lightweightLineRuntime } from "@/lib/lightweightChartRuntime";
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
  FlintChartDrawingLineSeriesRenderSpec,
  FlintChartDrawingRenderPlan,
  FlintChartDrawingPriceLineRenderSpec,
  FlintChartDrawingDraftResult,
  FlintChartDrawingHandleId,
  FlintChartDrawingMoveDelta,
} from "@flinttrade/design-system";
import type {
  DrawToolType,
  Drawing,
  DrawingPoint,
  DrawingSeriesMap,
  HlineRef,
} from "./types";

function getCanvasPriceTolerance(
  candle: ISeriesApi<"Candlestick">,
  y: number,
  price: number,
): number {
  const upper = candle.coordinateToPrice(y - 6);
  const lower = candle.coordinateToPrice(y + 6);
  if (upper != null && lower != null && Number.isFinite(upper) && Number.isFinite(lower)) {
    return Math.max(Math.abs(upper - lower), Math.abs(price) * 0.0005, 0.01);
  }
  return Math.max(Math.abs(price) * 0.001, 0.01);
}

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

interface UseDrawingToolsOptions {
  containerRef: React.RefObject<HTMLDivElement | null>;
  chartRef: React.MutableRefObject<IChartApi | null>;
  candleRef: React.MutableRefObject<ISeriesApi<"Candlestick"> | null>;
  markersPluginRef: React.MutableRefObject<ISeriesMarkersPluginApi<Time> | null>;
  drawMode: DrawToolType | null;
  setDrawMode: React.Dispatch<React.SetStateAction<DrawToolType | null>>;
  drawings: Drawing[];
  setDrawings: React.Dispatch<React.SetStateAction<Drawing[]>>;
  selectedDrawingId?: string | null;
  onDrawingCreated?: (drawingId: string) => void;
  onDrawingHit?: (drawingId: string | null) => void;
  onDrawingMove?: (drawingId: string, delta: FlintChartDrawingMoveDelta) => void;
  onDrawingHandleMove?: (
    drawingId: string,
    handle: FlintChartDrawingHandleId,
    delta: FlintChartDrawingMoveDelta,
  ) => void;
  pendingPoint: DrawingPoint | null;
  setPendingPoint: React.Dispatch<React.SetStateAction<DrawingPoint | null>>;
  pendingPoints?: DrawingPoint[];
  setPendingPoints?: React.Dispatch<React.SetStateAction<DrawingPoint[]>>;
  setAwaitingText: React.Dispatch<React.SetStateAction<DrawingPoint | null>>;
}

export function useDrawingTools({
  containerRef,
  chartRef,
  candleRef,
  markersPluginRef,
  drawMode,
  setDrawMode,
  drawings,
  setDrawings,
  selectedDrawingId,
  onDrawingCreated,
  onDrawingHit,
  onDrawingMove,
  onDrawingHandleMove,
  pendingPoint,
  setPendingPoint,
  pendingPoints = [],
  setPendingPoints,
  setAwaitingText,
}: UseDrawingToolsOptions) {
  // Refs so click handler closures always see the latest values
  const drawModeRef = useRef<DrawToolType | null>(drawMode);
  const pendingPointRef = useRef<DrawingPoint | null>(pendingPoint);
  const pendingPointsRef = useRef<DrawingPoint[]>(pendingPoints);
  const drawingsRef = useRef<Drawing[]>(drawings);
  const selectedDrawingIdRef = useRef<string | null | undefined>(selectedDrawingId);
  const onDrawingHitRef = useRef<typeof onDrawingHit>(onDrawingHit);
  const onDrawingCreatedRef = useRef<typeof onDrawingCreated>(onDrawingCreated);
  const onDrawingMoveRef = useRef<typeof onDrawingMove>(onDrawingMove);
  const onDrawingHandleMoveRef = useRef<typeof onDrawingHandleMove>(onDrawingHandleMove);
  const lastNativeDrawingClickRef = useRef(0);
  const dragStateRef = useRef<{
    kind: "drawing" | "handle";
    drawingId: string;
    handle?: FlintChartDrawingHandleId;
    lastPrice: number;
    lastTime?: Time;
  } | null>(null);
  const brushDraftRef = useRef<DrawingPoint[] | null>(null);
  const clickHandlerRef = useRef<((param: MouseEventParams) => void) | null>(null);
  const drawingSeriesRef = useRef<DrawingSeriesMap>(new Map());
  const hlineSeriesRef = useRef<Map<string, HlineRef>>(new Map());
  const drawingRenderPlanRef = useRef<FlintChartDrawingRenderPlan<Time>>({
    lineSeries: [],
    priceLines: [],
    markers: [],
  });
  const textMarkersRef = useRef<SeriesMarker<Time>[]>([]);

  useEffect(() => { drawModeRef.current = drawMode; }, [drawMode]);
  useEffect(() => { pendingPointRef.current = pendingPoint; }, [pendingPoint]);
  useEffect(() => { pendingPointsRef.current = pendingPoints; }, [pendingPoints]);
  useEffect(() => { drawingsRef.current = drawings; }, [drawings]);
  useEffect(() => { selectedDrawingIdRef.current = selectedDrawingId; }, [selectedDrawingId]);
  useEffect(() => { onDrawingHitRef.current = onDrawingHit; }, [onDrawingHit]);
  useEffect(() => { onDrawingCreatedRef.current = onDrawingCreated; }, [onDrawingCreated]);
  useEffect(() => { onDrawingMoveRef.current = onDrawingMove; }, [onDrawingMove]);
  useEffect(() => { onDrawingHandleMoveRef.current = onDrawingHandleMove; }, [onDrawingHandleMove]);

  const applyDrawingDraft = useCallback((creation: FlintChartDrawingDraftResult<Time>) => {
    const nextPendingPoints = (creation.pendingPoints ?? []) as DrawingPoint[];
    pendingPointRef.current = creation.pendingPoint;
    pendingPointsRef.current = nextPendingPoints;
    setPendingPoint(creation.pendingPoint);
    setPendingPoints?.(nextPendingPoints);
    setAwaitingText(creation.awaitingText);
    if (creation.drawing) {
      setDrawings((prev) => [...prev, creation.drawing as Drawing]);
      onDrawingCreated?.(creation.drawing.id);
    }
  }, [onDrawingCreated, setAwaitingText, setDrawings, setPendingPoint, setPendingPoints]);

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
      if (!param || !param.point) return;
      const price = candle.coordinateToPrice(param.point.y);
      if (price == null) return;
      const time = param.time as Time | undefined;

      if (!mode) {
        const hit = findFlintChartDrawingHit<Time>(
          drawingsRef.current,
          { ...(time != null ? { time } : {}), price },
          { priceTolerance: getCanvasPriceTolerance(candle, param.point.y, price) },
        );
        onDrawingHitRef.current?.(hit?.id ?? null);
        return;
      }

      if (mode === "eraser" || mode === "brush") return;

      if (Date.now() - lastNativeDrawingClickRef.current < 250) return;
      if (time == null) return;

      const point: DrawingPoint = { time, price };
      const creation = advanceFlintChartDrawingDraft<Time>({
        tool: mode,
        point,
        pendingPoint: pendingPointRef.current,
        pendingPoints: pendingPointsRef.current,
      });

      applyDrawingDraft(creation);
    };

    clickHandlerRef.current = handler;
    chart.subscribeClick(handler);

    return () => {
      chart.unsubscribeClick(handler);
      clickHandlerRef.current = null;
    };
  // drawMode is intentionally the only dep — the handler body reads live refs
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [drawMode, applyDrawingDraft]);

  useEffect(() => {
    const container = containerRef.current;
    const chart = chartRef.current;
    const candle = candleRef.current;
    if (!container || !chart || !candle) return;
    const activeChart = chart;

    function pointFromPointer(event: PointerEvent) {
      if (!container || !chart || !candle) return null;
      const rect = container.getBoundingClientRect();
      const x = event.clientX - rect.left;
      const y = event.clientY - rect.top;
      const price = candle.coordinateToPrice(y);
      if (price == null || !Number.isFinite(price)) return null;
      let time: Time | undefined;
      try {
        const timeScale = activeChart.timeScale() as unknown as {
          coordinateToTime?: (coordinate: number) => Time | null;
        };
        const pointerTime = timeScale.coordinateToTime?.(x);
        if (pointerTime != null) time = pointerTime;
      } catch { /* ignore */ }
      return { price, time, x, y };
    }

    function getCanvasTimeTolerance(x: number): number {
      try {
        const timeScale = activeChart.timeScale() as unknown as {
          coordinateToTime?: (coordinate: number) => Time | null;
        };
        const leftTime = timeScale.coordinateToTime?.(x - 8);
        const rightTime = timeScale.coordinateToTime?.(x + 8);
        const delta =
          leftTime != null && rightTime != null
            ? getFlintChartTimeDelta(leftTime, rightTime)
            : null;
        return delta != null && Number.isFinite(delta)
          ? Math.max(1, Math.abs(delta))
          : 2;
      } catch {
        return 2;
      }
    }

    function appendBrushPoint(point: DrawingPoint) {
      const points = brushDraftRef.current ?? [];
      const lastPoint = points.at(-1);
      if (
        lastPoint &&
        lastPoint.time === point.time &&
        Math.abs(lastPoint.price - point.price) < 0.000001
      ) {
        return;
      }
      const nextPoints = [...points, point];
      brushDraftRef.current = nextPoints;
      pendingPointRef.current = point;
      pendingPointsRef.current = nextPoints;
      setPendingPoint(point);
      setPendingPoints?.(nextPoints);
    }

    const handlePointerDown = (event: PointerEvent) => {
      const activeMode = drawModeRef.current;
      if (activeMode) {
        if (event.button !== 0 && event.buttons !== 1) return;
        const pointerPoint = pointFromPointer(event);
        if (!pointerPoint) return;
        if (activeMode === "eraser") {
          const priceTolerance = getCanvasPriceTolerance(candle, pointerPoint.y, pointerPoint.price);
          const timeTolerance = getCanvasTimeTolerance(pointerPoint.x);
          const hit = findFlintChartDrawingHit<Time>(
            drawingsRef.current,
            { ...(pointerPoint.time != null ? { time: pointerPoint.time } : {}), price: pointerPoint.price },
            { priceTolerance, timeTolerance },
          );
          if (!hit || hit.locked === true) return;
          setDrawings((prev) => removeFlintChartDrawingById(prev, hit.id) as Drawing[]);
          onDrawingHitRef.current?.(null);
          setPendingPoint(null);
          pendingPointsRef.current = [];
          setPendingPoints?.([]);
          setAwaitingText(null);
          event.preventDefault();
          return;
        }
        if (activeMode === "brush") {
          if (pointerPoint.time == null) return;
          const point: DrawingPoint = { time: pointerPoint.time, price: pointerPoint.price };
          lastNativeDrawingClickRef.current = Date.now();
          brushDraftRef.current = [];
          appendBrushPoint(point);
          setAwaitingText(null);
          try { container.setPointerCapture(event.pointerId); } catch { /* ignore */ }
          event.preventDefault();
          return;
        }
        if (pointerPoint.time == null) return;
        lastNativeDrawingClickRef.current = Date.now();
        applyDrawingDraft(advanceFlintChartDrawingDraft<Time>({
          tool: activeMode,
          point: { time: pointerPoint.time, price: pointerPoint.price },
          pendingPoint: pendingPointRef.current,
          pendingPoints: pendingPointsRef.current,
        }));
        event.preventDefault();
        return;
      }

      if (event.button !== 0 && event.buttons !== 1) return;
      const selectedId = selectedDrawingIdRef.current;
      if (!selectedId || !onDrawingMoveRef.current) return;
      const point = pointFromPointer(event);
      if (!point) return;
      const priceTolerance = getCanvasPriceTolerance(candle, point.y, point.price);
      const timeTolerance = getCanvasTimeTolerance(point.x);
      const handleHit = findFlintChartDrawingHandleHit<Time>(
        drawingsRef.current,
        selectedId,
        { ...(point.time != null ? { time: point.time } : {}), price: point.price },
        { priceTolerance, timeTolerance },
      );
      const hit = handleHit
        ? drawingsRef.current.find((drawing) => drawing.id === selectedId)
        : findFlintChartDrawingHit<Time>(
          drawingsRef.current,
          { ...(point.time != null ? { time: point.time } : {}), price: point.price },
          { priceTolerance, timeTolerance },
        );
      if (!hit || hit.id !== selectedId || hit.locked === true) return;
      dragStateRef.current = handleHit && onDrawingHandleMoveRef.current
        ? {
            kind: "handle",
            drawingId: selectedId,
            handle: handleHit.handle,
            lastPrice: point.price,
            lastTime: point.time,
          }
        : {
            kind: "drawing",
            drawingId: selectedId,
            lastPrice: point.price,
            lastTime: point.time,
          };
      try { container.setPointerCapture(event.pointerId); } catch { /* ignore */ }
      event.preventDefault();
    };

    const handlePointerMove = (event: PointerEvent) => {
      if (brushDraftRef.current && drawModeRef.current === "brush") {
        const point = pointFromPointer(event);
        if (!point || point.time == null) return;
        appendBrushPoint({ time: point.time, price: point.price });
        event.preventDefault();
        return;
      }
      const drag = dragStateRef.current;
      if (!drag) return;
      const point = pointFromPointer(event);
      if (!point) return;
      const priceDelta = point.price - drag.lastPrice;
      const timeDelta =
        drag.lastTime != null && point.time != null
          ? getFlintChartTimeDelta(drag.lastTime, point.time)
          : null;
      const delta: FlintChartDrawingMoveDelta = {};
      if (Number.isFinite(priceDelta) && Math.abs(priceDelta) > 0.000001) {
        delta.priceDelta = priceDelta;
      }
      if (timeDelta != null && Number.isFinite(timeDelta) && Math.abs(timeDelta) > 0.000001) {
        delta.timeDelta = timeDelta;
      }
      if (delta.priceDelta != null || delta.timeDelta != null) {
        if (drag.kind === "handle" && drag.handle) {
          onDrawingHandleMoveRef.current?.(drag.drawingId, drag.handle, delta);
        } else {
          onDrawingMoveRef.current?.(drag.drawingId, delta);
        }
        dragStateRef.current = {
          kind: drag.kind,
          drawingId: drag.drawingId,
          ...(drag.handle ? { handle: drag.handle } : {}),
          lastPrice: point.price,
          lastTime: point.time,
        };
      }
      event.preventDefault();
    };

    const handlePointerEnd = (event: PointerEvent) => {
      if (brushDraftRef.current) {
        const drawing = createFlintChartBrushDrawing<Time>(brushDraftRef.current);
        brushDraftRef.current = null;
        pendingPointRef.current = null;
        pendingPointsRef.current = [];
        setPendingPoint(null);
        setPendingPoints?.([]);
        setAwaitingText(null);
        if (drawing) {
          setDrawings((prev) => [...prev, drawing as Drawing]);
          onDrawingCreatedRef.current?.(drawing.id);
        }
        try { container.releasePointerCapture(event.pointerId); } catch { /* ignore */ }
        event.preventDefault();
        return;
      }
      if (!dragStateRef.current) return;
      dragStateRef.current = null;
      try { container.releasePointerCapture(event.pointerId); } catch { /* ignore */ }
    };

    container.addEventListener("pointerdown", handlePointerDown, { capture: true });
    window.addEventListener("pointermove", handlePointerMove);
    window.addEventListener("pointerup", handlePointerEnd);
    window.addEventListener("pointercancel", handlePointerEnd);

    return () => {
      container.removeEventListener("pointerdown", handlePointerDown, { capture: true });
      window.removeEventListener("pointermove", handlePointerMove);
      window.removeEventListener("pointerup", handlePointerEnd);
      window.removeEventListener("pointercancel", handlePointerEnd);
      dragStateRef.current = null;
      brushDraftRef.current = null;
    };
  }, [applyDrawingDraft, candleRef, chartRef, containerRef, setAwaitingText, setDrawings, setPendingPoint, setPendingPoints]);

  // --- Reconcile drawings whenever the core render plan changes ---
  useEffect(() => {
    const chart = chartRef.current;
    const candle = candleRef.current;
    if (!chart || !candle) return;

    const dsMap = drawingSeriesRef.current;
    const priceLineMap = hlineSeriesRef.current;
    const renderPlan = createFlintChartDrawingRenderPlan(drawings, selectedDrawingId);
    const renderPlanDiff = createFlintChartDrawingRenderPlanDiff(drawingRenderPlanRef.current, renderPlan);
    const markers = renderPlan.markers as SeriesMarker<Time>[];

    const addLineSeries = (lineSeriesSpec: FlintChartDrawingLineSeriesRenderSpec<Time>) => {
      try {
        const s = lightweightLineRuntime.addLineSeries(chart, lineSeriesSpec.options);
        s.setData(lineSeriesSpec.data as LineData[]);
        dsMap.set(lineSeriesSpec.key, s);
      } catch { /* ignore */ }
    };

    const updateLineSeries = (lineSeriesSpec: FlintChartDrawingLineSeriesRenderSpec<Time>) => {
      const series = dsMap.get(lineSeriesSpec.key);
      if (!series) {
        addLineSeries(lineSeriesSpec);
        return;
      }
      try {
        series.applyOptions(lineSeriesSpec.options);
        series.setData(lineSeriesSpec.data as LineData[]);
      } catch {
        try { chart.removeSeries(series); } catch { /* ignore */ }
        dsMap.delete(lineSeriesSpec.key);
        addLineSeries(lineSeriesSpec);
      }
    };

    const removeLineSeries = (lineSeriesSpec: FlintChartDrawingLineSeriesRenderSpec<Time>) => {
      const series = dsMap.get(lineSeriesSpec.key);
      if (!series) return;
      try { chart.removeSeries(series); } catch { /* ignore */ }
      dsMap.delete(lineSeriesSpec.key);
    };

    const addPriceLine = (priceLineSpec: FlintChartDrawingPriceLineRenderSpec) => {
      try {
        const priceLine = candle.createPriceLine(priceLineSpec.priceLine);
        priceLineMap.set(priceLineSpec.key, {
          _key: priceLineSpec.key,
          _priceLine: priceLine,
          _series: candle,
        });
      } catch { /* ignore */ }
    };

    const removePriceLine = (priceLineSpec: FlintChartDrawingPriceLineRenderSpec) => {
      const ref = priceLineMap.get(priceLineSpec.key);
      if (!ref) return;
      try { ref._series.removePriceLine(ref._priceLine); } catch { /* ignore */ }
      priceLineMap.delete(priceLineSpec.key);
    };

    for (const lineSeriesSpec of renderPlanDiff.lineSeries.removed) {
      removeLineSeries(lineSeriesSpec);
    }

    for (const lineSeriesSpec of renderPlanDiff.lineSeries.updated) {
      updateLineSeries(lineSeriesSpec);
    }

    for (const lineSeriesSpec of renderPlanDiff.lineSeries.added) {
      addLineSeries(lineSeriesSpec);
    }

    for (const priceLineSpec of renderPlanDiff.priceLines.removed) {
      removePriceLine(priceLineSpec);
    }

    for (const priceLineSpec of renderPlanDiff.priceLines.updated) {
      removePriceLine(priceLineSpec);
      addPriceLine(priceLineSpec);
    }

    for (const priceLineSpec of renderPlanDiff.priceLines.added) {
      addPriceLine(priceLineSpec);
    }

    if (markersPluginRef.current && renderPlanDiff.markersChanged) {
      try {
        markersPluginRef.current.setMarkers(markers);
        textMarkersRef.current = markers;
      } catch { /* ignore */ }
    }

    drawingRenderPlanRef.current = renderPlan;
  }, [drawings, selectedDrawingId, chartRef, candleRef, markersPluginRef]);

  useEffect(() => {
    return () => {
      const chart = chartRef.current;
      const dsMap = drawingSeriesRef.current;
      if (chart) {
        for (const series of dsMap.values()) {
          try { chart.removeSeries(series); } catch { /* ignore */ }
        }
      }
      dsMap.clear();
      for (const ref of hlineSeriesRef.current.values()) {
        try { ref._series.removePriceLine(ref._priceLine); } catch { /* gone */ }
      }
      hlineSeriesRef.current.clear();
      drawingRenderPlanRef.current = { lineSeries: [], priceLines: [], markers: [] };
    };
  }, [chartRef]);

  // --- Convenience actions returned to the caller ---
  const toggleDrawMode = useCallback((mode: DrawToolType) => {
    setDrawMode((prev) => {
      if (mode === "cursor") {
        brushDraftRef.current = null;
        pendingPointsRef.current = [];
        setPendingPoint(null);
        setPendingPoints?.([]);
        return null;
      }
      if (prev === mode) {
        brushDraftRef.current = null;
        pendingPointsRef.current = [];
        setPendingPoint(null);
        setPendingPoints?.([]);
        return null;
      }
      brushDraftRef.current = null;
      pendingPointsRef.current = [];
      setPendingPoint(null);
      setPendingPoints?.([]);
      return mode;
    });
  }, [setDrawMode, setPendingPoint, setPendingPoints]);

  const clearAllDrawings = useCallback(() => {
    setDrawings([]);
    brushDraftRef.current = null;
    pendingPointsRef.current = [];
    setPendingPoint(null);
    setPendingPoints?.([]);
  }, [setDrawings, setPendingPoint, setPendingPoints]);

  const undoLastDrawing = useCallback(() => {
    setDrawings((prev) => prev.slice(0, -1));
  }, [setDrawings]);

  // Expose the internal series refs for cleanup on symbol change.
  return {
    drawingSeriesRef,
    hlineSeriesRef,
    toggleDrawMode,
    clearAllDrawings,
    undoLastDrawing,
  };
}
