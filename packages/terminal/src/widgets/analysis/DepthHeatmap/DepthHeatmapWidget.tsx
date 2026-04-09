/**
 * DepthHeatmapWidget — Canvas-based depth heatmap for FlintTrade terminal.
 *
 * Visualises bid/ask volume distribution at different price levels over time,
 * inspired by NinjaTrader and Sierra Chart depth maps.
 *
 * Layout:
 *   Y-axis: price levels (tick-by-tick)
 *   X-axis: time (scrolling left, newest on right)
 *   Color intensity: volume at that price level (darker = less, brighter = more)
 *   Bid side: blue/cyan tones
 *   Ask side: red/orange tones
 *   Current price: highlighted horizontal line
 *   Large orders: brighter/white-hot colors
 *
 * Data: synthetic depth data (200 price levels x 50 time columns) with
 * auto-update simulation (shifts data left, adds new column every 1s).
 *
 * Performance (multi-layer canvas):
 *   - Layer 1 (canvasRef): main heatmap — repaints ONLY when data changes.
 *     This is the expensive draw (fills every cell), so we avoid triggering
 *     it on mouse moves.
 *   - Layer 2 (crosshairCanvasRef): crosshair overlay — repaints on every
 *     mouse move at up to 60 fps. It sits on top of the heatmap canvas at
 *     z-index 1 and is cleared on mouse leave. Because it is a separate
 *     canvas, the main heatmap canvas is never touched during mouse moves,
 *     eliminating the single most common source of jank in canvas UIs.
 *   - ResizeObserver keeps both canvases in sync with the container DPR.
 *   - requestAnimationFrame gates prevent redundant repaints on each layer.
 *
 * Accessibility:
 *   - Canvas has role="img" and aria-label describing the view
 *   - Symbol selector has visible label via sr-only span
 */

import { useRef, useEffect, useState, useCallback, memo, type MouseEvent as ReactMouseEvent } from "react";
import { Flame } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  generateDepthHeatmapData,
  shiftAndAppendColumn,
} from "./depthHeatmapData";
import type { DepthHeatmapData } from "./depthHeatmapData";

// ─── Constants ────────────────────────────────────────────────────────────────

const SYMBOLS = ["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "RELIANCE", "TCS"];

const MARGIN_RIGHT = 64; // price labels
const MARGIN_LEFT = 4;
const MARGIN_TOP = 4;
const MARGIN_BOTTOM = 20; // time labels

const COLOR_CANVAS_BG = "#0a0a0f";
const COLOR_GRID = "#2a2a3a";
const COLOR_TEXT = "#a1a1aa";
const COLOR_TEXT_PRICE = "#e4e4e7";
const COLOR_LTP_LINE = "#ffffff";

// ─── Color interpolation helpers ─────────────────────────────────────────────

interface RGB {
  r: number;
  g: number;
  b: number;
}

/** Bid color ramp: dark blue → cyan → white */
const BID_RAMP: RGB[] = [
  { r: 10, g: 15, b: 40 },    // near zero: very dark blue
  { r: 15, g: 50, b: 120 },   // low: dark blue
  { r: 30, g: 100, b: 200 },  // medium: blue
  { r: 50, g: 180, b: 230 },  // high: cyan
  { r: 180, g: 240, b: 255 }, // very high: bright cyan
  { r: 255, g: 255, b: 255 }, // extreme: white-hot
];

/** Ask color ramp: dark red → orange → white */
const ASK_RAMP: RGB[] = [
  { r: 40, g: 10, b: 10 },    // near zero: very dark red
  { r: 120, g: 30, b: 15 },   // low: dark red
  { r: 200, g: 60, b: 30 },   // medium: red
  { r: 230, g: 130, b: 50 },  // high: orange
  { r: 255, g: 210, b: 150 }, // very high: bright orange
  { r: 255, g: 255, b: 255 }, // extreme: white-hot
];

function lerpRGB(a: RGB, b: RGB, t: number): RGB {
  return {
    r: Math.round(a.r + (b.r - a.r) * t),
    g: Math.round(a.g + (b.g - a.g) * t),
    b: Math.round(a.b + (b.b - a.b) * t),
  };
}

function colorFromRamp(ramp: RGB[], intensity: number): RGB {
  // intensity: 0 to 1
  const clamped = Math.max(0, Math.min(1, intensity));
  const segments = ramp.length - 1;
  const pos = clamped * segments;
  const idx = Math.min(Math.floor(pos), segments - 1);
  const frac = pos - idx;
  return lerpRGB(ramp[idx], ramp[idx + 1], frac);
}

function rgbToString(c: RGB): string {
  return `rgb(${c.r},${c.g},${c.b})`;
}

// ─── Drawing ─────────────────────────────────────────────────────────────────

function drawHeatmap(
  ctx: CanvasRenderingContext2D,
  data: DepthHeatmapData,
  physicalWidth: number,
  physicalHeight: number,
  dpr: number,
): void {
  ctx.fillStyle = COLOR_CANVAS_BG;
  ctx.fillRect(0, 0, physicalWidth, physicalHeight);

  const numLevels = data.priceLevels.length;
  const numColumns = data.timeLabels.length;
  if (numLevels === 0 || numColumns === 0) return;

  const css = (px: number) => px * dpr;

  const chartLeft = css(MARGIN_LEFT);
  const chartRight = physicalWidth - css(MARGIN_RIGHT);
  const chartTop = css(MARGIN_TOP);
  const chartBottom = physicalHeight - css(MARGIN_BOTTOM);
  const chartWidth = chartRight - chartLeft;
  const chartHeight = chartBottom - chartTop;

  if (chartWidth <= 0 || chartHeight <= 0) return;

  const cellW = chartWidth / numColumns;
  const cellH = chartHeight / numLevels;

  const maxVol = Math.max(data.maxVolume, 1);

  // Use power scale for better visual contrast (gamma = 0.5 = sqrt)
  const gamma = 0.5;

  // ─── Draw heatmap cells ────────────────────────────────────────────────────
  // Draw from bottom (low price) to top (high price), left (old) to right (new)
  for (let p = 0; p < numLevels; p++) {
    const row = data.grid[p];
    // Y: price index 0 = lowest price at bottom
    const y = chartBottom - (p + 1) * cellH;

    for (let t = 0; t < numColumns; t++) {
      const cell = row[t];
      if (!cell) continue;

      const x = chartLeft + t * cellW;
      const totalVol = cell.bidVolume + cell.askVolume;
      if (totalVol === 0) continue;

      // Determine dominant side and intensity
      const dominantBid = cell.bidVolume >= cell.askVolume;
      const dominantVol = dominantBid ? cell.bidVolume : cell.askVolume;
      const intensity = Math.pow(dominantVol / maxVol, gamma);

      const ramp = dominantBid ? BID_RAMP : ASK_RAMP;
      const color = colorFromRamp(ramp, intensity);

      ctx.fillStyle = rgbToString(color);
      ctx.fillRect(x, y, Math.ceil(cellW) + 1, Math.ceil(cellH) + 1);
    }
  }

  // ─── Current price line ────────────────────────────────────────────────────
  const ltpY = chartBottom - (data.currentPriceIndex + 0.5) * cellH;
  ctx.save();
  ctx.strokeStyle = COLOR_LTP_LINE;
  ctx.lineWidth = dpr;
  ctx.globalAlpha = 0.7;
  ctx.setLineDash([css(4), css(3)]);
  ctx.beginPath();
  ctx.moveTo(chartLeft, ltpY);
  ctx.lineTo(chartRight, ltpY);
  ctx.stroke();
  ctx.restore();

  // ─── Price scale (right margin) ────────────────────────────────────────────
  ctx.save();
  ctx.fillStyle = COLOR_TEXT_PRICE;
  ctx.font = `${css(9)}px "JetBrains Mono", monospace`;
  ctx.textAlign = "left";
  ctx.textBaseline = "middle";

  const maxLabels = Math.floor(chartHeight / css(16));
  const step = Math.max(1, Math.ceil(numLevels / maxLabels));

  for (let i = 0; i < numLevels; i += step) {
    const y = chartBottom - (i + 0.5) * cellH;
    const price = data.priceLevels[i];
    ctx.fillText(price.toFixed(1), chartRight + css(4), y);
  }

  // LTP label — highlighted
  ctx.fillStyle = COLOR_LTP_LINE;
  ctx.font = `bold ${css(9)}px "JetBrains Mono", monospace`;
  const ltpPrice = data.priceLevels[data.currentPriceIndex];
  ctx.fillText(
    ltpPrice.toFixed(1),
    chartRight + css(4),
    ltpY,
  );
  ctx.restore();

  // ─── Time labels (bottom margin) ───────────────────────────────────────────
  ctx.save();
  ctx.fillStyle = COLOR_TEXT;
  ctx.font = `${css(8)}px "JetBrains Mono", monospace`;
  ctx.textAlign = "center";
  ctx.textBaseline = "top";

  // Show every Nth time label to avoid overcrowding
  const maxTimeLabels = Math.floor(chartWidth / css(48));
  const timeStep = Math.max(1, Math.ceil(numColumns / maxTimeLabels));

  for (let t = 0; t < numColumns; t += timeStep) {
    const x = chartLeft + (t + 0.5) * cellW;
    // Show just MM:SS for compactness
    const label = data.timeLabels[t];
    const short = label.slice(3); // strip hour, show MM:SS
    ctx.fillText(short, x, chartBottom + css(3));
  }
  ctx.restore();

  // ─── Grid border ───────────────────────────────────────────────────────────
  ctx.save();
  ctx.strokeStyle = COLOR_GRID;
  ctx.lineWidth = dpr;
  ctx.strokeRect(chartLeft, chartTop, chartWidth, chartHeight);
  ctx.restore();
}

// ─── Volume legend (draws on canvas overlay area) ────────────────────────────

function drawLegend(
  ctx: CanvasRenderingContext2D,
  physicalWidth: number,
  dpr: number,
  maxVolume: number,
): void {
  const css = (px: number) => px * dpr;

  const legendW = css(12);
  const legendH = css(80);
  const legendX = physicalWidth - css(MARGIN_RIGHT) + css(44);
  const legendY = css(MARGIN_TOP + 4);

  // Draw bid gradient (bottom half)
  const halfH = legendH / 2;
  for (let i = 0; i < Math.ceil(halfH); i++) {
    const t = i / halfH;
    const color = colorFromRamp(BID_RAMP, t);
    ctx.fillStyle = rgbToString(color);
    ctx.fillRect(legendX, legendY + legendH - i, legendW, 2);
  }

  // Draw ask gradient (top half)
  for (let i = 0; i < Math.ceil(halfH); i++) {
    const t = i / halfH;
    const color = colorFromRamp(ASK_RAMP, t);
    ctx.fillStyle = rgbToString(color);
    ctx.fillRect(legendX, legendY + halfH - i, legendW, 2);
  }

  // Labels
  ctx.save();
  ctx.fillStyle = COLOR_TEXT;
  ctx.font = `${css(7)}px "JetBrains Mono", monospace`;
  ctx.textAlign = "center";
  ctx.textBaseline = "top";
  ctx.fillText("Ask", legendX + legendW / 2, legendY - css(10));
  ctx.fillText("Bid", legendX + legendW / 2, legendY + legendH + css(2));

  // Volume scale
  ctx.textAlign = "left";
  ctx.fillText(String(maxVolume), legendX + legendW + css(2), legendY);
  ctx.fillText("0", legendX + legendW + css(2), legendY + legendH - css(8));
  ctx.restore();
}

// ─── Crosshair drawing (layer 2 — mouse-only repaint) ────────────────────────

/**
 * Draw a full-canvas crosshair at the given CSS pixel coordinates onto the
 * dedicated crosshair canvas.  The crosshair canvas is separate from the
 * main heatmap canvas so the heatmap does not need to repaint on mouse moves.
 *
 * @param ctx    2D context of the crosshair canvas.
 * @param cssX   Mouse X in CSS pixels (before DPR scaling).
 * @param cssY   Mouse Y in CSS pixels (before DPR scaling).
 * @param physW  Physical canvas width (CSS × DPR).
 * @param physH  Physical canvas height (CSS × DPR).
 * @param dpr    Device pixel ratio.
 */
function drawCrosshair(
  ctx: CanvasRenderingContext2D,
  cssX: number,
  cssY: number,
  physW: number,
  physH: number,
  dpr: number,
): void {
  ctx.clearRect(0, 0, physW, physH);

  const x = cssX * dpr;
  const y = cssY * dpr;

  ctx.save();
  ctx.strokeStyle = "rgba(255,255,255,0.35)";
  ctx.lineWidth = dpr;
  ctx.setLineDash([dpr * 3, dpr * 3]);

  // Horizontal line
  ctx.beginPath();
  ctx.moveTo(0, y);
  ctx.lineTo(physW, y);
  ctx.stroke();

  // Vertical line
  ctx.beginPath();
  ctx.moveTo(x, 0);
  ctx.lineTo(x, physH);
  ctx.stroke();

  ctx.restore();
}

// ─── Main widget ──────────────────────────────────────────────────────────────

function DepthHeatmapWidget() {
  const [symbol, setSymbol] = useState("NIFTY");

  // Layer 1: main heatmap canvas — repaints on data change only
  const canvasRef = useRef<HTMLCanvasElement>(null);
  // Layer 2: crosshair overlay canvas — repaints on mouse move at 60 fps
  const crosshairCanvasRef = useRef<HTMLCanvasElement>(null);

  const containerRef = useRef<HTMLDivElement>(null);
  const rafRef = useRef<number | null>(null);
  const crosshairRafRef = useRef<number | null>(null);
  const sizeRef = useRef({ width: 0, height: 0 });
  const dataRef = useRef<DepthHeatmapData | null>(null);
  const seedRef = useRef(42);

  // Initialize data on symbol change
  useEffect(() => {
    // Different seed per symbol for variety
    const symbolSeed = symbol.split("").reduce((acc, ch) => acc + ch.charCodeAt(0), 0);
    seedRef.current = symbolSeed;
    dataRef.current = generateDepthHeatmapData(200, 50, symbolSeed);
  }, [symbol]);

  // Paint function
  const paint = useCallback(() => {
    if (rafRef.current !== null) return;
    rafRef.current = requestAnimationFrame(() => {
      rafRef.current = null;
      const canvas = canvasRef.current;
      if (!canvas) return;
      const ctx = canvas.getContext("2d");
      if (!ctx) return;
      const data = dataRef.current;
      if (!data) return;

      const dpr = window.devicePixelRatio || 1;
      drawHeatmap(ctx, data, canvas.width, canvas.height, dpr);
      drawLegend(ctx, canvas.width, dpr, data.maxVolume);
    });
  }, []);

  // ResizeObserver
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const observer = new ResizeObserver((entries) => {
      const entry = entries[0];
      if (!entry) return;
      const { width, height } = entry.contentRect;
      if (
        Math.abs(width - sizeRef.current.width) < 1 &&
        Math.abs(height - sizeRef.current.height) < 1
      ) {
        return;
      }
      sizeRef.current = { width, height };
      const canvas = canvasRef.current;
      if (!canvas) return;
      const dpr = window.devicePixelRatio || 1;
      const physW = Math.floor(width * dpr);
      const physH = Math.floor(height * dpr);

      // Resize main heatmap canvas (layer 1)
      canvas.width = physW;
      canvas.height = physH;
      canvas.style.width = `${width}px`;
      canvas.style.height = `${height}px`;

      // Resize crosshair canvas (layer 2) to match exactly
      const crosshairCanvas = crosshairCanvasRef.current;
      if (crosshairCanvas) {
        crosshairCanvas.width = physW;
        crosshairCanvas.height = physH;
        crosshairCanvas.style.width = `${width}px`;
        crosshairCanvas.style.height = `${height}px`;
      }

      paint();
    });

    observer.observe(container);
    return () => observer.disconnect();
  }, [paint]);

  // Auto-update simulation: shift data left, add new column every 1s.
  // Pauses when the page/tab is hidden (e.g. minimised, background tab) to
  // avoid wasting CPU on invisible updates.
  useEffect(() => {
    let interval: ReturnType<typeof setInterval> | null = null;

    function startInterval() {
      if (interval !== null) return;
      interval = setInterval(() => {
        if (!dataRef.current) return;
        seedRef.current += 1;
        dataRef.current = shiftAndAppendColumn(dataRef.current, seedRef.current);
        paint();
      }, 1000);
    }

    function stopInterval() {
      if (interval !== null) {
        clearInterval(interval);
        interval = null;
      }
    }

    function handleVisibilityChange() {
      if (document.visibilityState === "visible") {
        startInterval();
      } else {
        stopInterval();
      }
    }

    // Only start if the page is currently visible
    if (document.visibilityState === "visible") {
      startInterval();
    }

    document.addEventListener("visibilitychange", handleVisibilityChange);

    return () => {
      stopInterval();
      document.removeEventListener("visibilitychange", handleVisibilityChange);
    };
  }, [paint, symbol]);

  // Repaint on symbol change (data reinitializes)
  useEffect(() => {
    paint();
  }, [symbol, paint]);

  // Cleanup rAF on unmount — cancel both heatmap and crosshair frames
  useEffect(() => {
    return () => {
      if (rafRef.current !== null) {
        cancelAnimationFrame(rafRef.current);
      }
      if (crosshairRafRef.current !== null) {
        cancelAnimationFrame(crosshairRafRef.current);
      }
    };
  }, []);

  // ── Mouse handlers for crosshair (layer 2 only — never touches heatmap) ──

  const handleMouseMove = useCallback((e: ReactMouseEvent<HTMLDivElement>) => {
    // Throttle to one crosshair repaint per animation frame (60 fps cap)
    if (crosshairRafRef.current !== null) return;
    const rect = (e.currentTarget as HTMLDivElement).getBoundingClientRect();
    const cssX = e.clientX - rect.left;
    const cssY = e.clientY - rect.top;
    crosshairRafRef.current = requestAnimationFrame(() => {
      crosshairRafRef.current = null;
      const crosshairCanvas = crosshairCanvasRef.current;
      if (!crosshairCanvas) return;
      const ctx = crosshairCanvas.getContext("2d");
      if (!ctx) return;
      const dpr = window.devicePixelRatio || 1;
      drawCrosshair(ctx, cssX, cssY, crosshairCanvas.width, crosshairCanvas.height, dpr);
    });
  }, []);

  const handleMouseLeave = useCallback(() => {
    // Cancel any pending crosshair frame and clear the overlay
    if (crosshairRafRef.current !== null) {
      cancelAnimationFrame(crosshairRafRef.current);
      crosshairRafRef.current = null;
    }
    const crosshairCanvas = crosshairCanvasRef.current;
    if (!crosshairCanvas) return;
    const ctx = crosshairCanvas.getContext("2d");
    if (ctx) {
      ctx.clearRect(0, 0, crosshairCanvas.width, crosshairCanvas.height);
    }
  }, []);

  const currentPrice = dataRef.current
    ? dataRef.current.priceLevels[dataRef.current.currentPriceIndex]
    : 0;

  return (
    <div className="flex flex-col h-full bg-surface-base select-none">
      {/* ─── Toolbar ────────────────────────────────────────────────────── */}
      <div className="flex items-center gap-2 px-3 py-1.5 border-b border-border-default shrink-0">
        <Flame className="size-4 text-amber-400" aria-hidden="true" />
        <span className="text-xs font-medium text-text-secondary">Depth Heatmap</span>

        {/* Symbol selector */}
        <span className="sr-only" id="dh-symbol-label">
          Symbol
        </span>
        <Select value={symbol} onValueChange={setSymbol}>
          <SelectTrigger
            className="h-6 w-28 text-xs border-border-default bg-surface-card text-text-primary focus:ring-0"
            aria-labelledby="dh-symbol-label"
          >
            <SelectValue />
          </SelectTrigger>
          <SelectContent className="bg-surface-card border-border-default">
            {SYMBOLS.map((s) => (
              <SelectItem
                key={s}
                value={s}
                className="text-xs text-text-primary focus:bg-surface-active"
              >
                {s}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        {/* LTP */}
        <div className="ml-auto flex items-center gap-1.5">
          <span className="text-xs text-text-muted">LTP</span>
          <span className="font-mono text-xs font-semibold text-text-primary tabular-nums">
            {currentPrice > 0 ? currentPrice.toFixed(1) : "\u2014"}
          </span>
        </div>

        <Badge
          variant="outline"
          className="text-xs border-amber-500/40 text-amber-400 bg-amber-500/10 h-5 px-1.5"
          aria-label="Displaying synthetic depth data"
        >
          Synthetic
        </Badge>
      </div>

      {/* ─── Canvas (two-layer) ─────────────────────────────────────────── */}
      {/*
        Layer 1 (canvasRef):           main heatmap — repaints on data change.
        Layer 2 (crosshairCanvasRef):  crosshair overlay — repaints on mouse move.
        The crosshair canvas sits above the heatmap (z-10) and intercepts pointer
        events. The heatmap canvas has pointer-events:none so mouse events bubble
        up to the container, which forwards them to the crosshair handler.
      */}
      <div
        ref={containerRef}
        className="flex-1 relative min-h-0"
        data-testid="depthheatmap-container"
        role="img"
        aria-label={`Depth heatmap for ${symbol}. Shows bid volume (blue) and ask volume (red) at price levels over time. Brighter colors indicate higher volume. Current price highlighted with dashed white line.`}
        onMouseMove={handleMouseMove}
        onMouseLeave={handleMouseLeave}
      >
        {/* Layer 1: heatmap — expensive, only repaints when data changes */}
        <canvas
          ref={canvasRef}
          className="absolute inset-0 block pointer-events-none"
          data-testid="depthheatmap-canvas"
          aria-hidden="true"
        />
        {/* Layer 2: crosshair — cheap, repaints at 60 fps on mouse move */}
        <canvas
          ref={crosshairCanvasRef}
          className="absolute inset-0 block pointer-events-none"
          data-testid="depthheatmap-crosshair"
          aria-hidden="true"
          style={{ zIndex: 1 }}
        />
      </div>
    </div>
  );
}

export default memo(DepthHeatmapWidget);
