/**
 * OrderFlowWidget — Order Flow Footprint chart for FlintTrade terminal.
 *
 * Visualises order flow as a footprint chart using Canvas2D (NOT SVG, NOT DOM).
 * Each column = one time bucket. Each row within a column = a price level.
 * Bid (buy) volume extends right as a green bar. Ask (sell) volume extends
 * left as a red bar. The POC (Point of Control — highest total volume) is
 * highlighted per column with a yellow border.
 *
 * Data is fetched from the FlintTrade backend via the useOrderFlow hook
 * (GET /ft-api/v1/orderflow). The backend currently returns synthetic
 * footprint data; when the live WebSocket tick pipeline is wired, the
 * same endpoint will serve real aggregated order flow buckets.
 *
 * Canvas layout:
 *   left margin  = 12px  (minimal — bars face outward, no label needed)
 *   right margin = 56px  (price scale labels)
 *   top margin   = 8px
 *   bottom margin = 24px (time scale labels)
 *
 * Performance:
 *   - All drawing is on a single HTMLCanvasElement (no DOM per cell).
 *   - ResizeObserver keeps canvas resolution in sync with container DPR.
 *   - requestAnimationFrame gate prevents redundant repaints.
 *   - useMemo to avoid recomputing sample data on every keystroke.
 *
 * Accessibility:
 *   - Canvas has role="img" and aria-label describing the current view.
 *   - Symbol and interval selectors have visible labels via sr-only span.
 *   - "Sample Data" badge includes screen-reader text.
 */

import {
  useRef,
  useEffect,
  useState,
  useMemo,
  useCallback,
  memo,
} from "react";
import { AlertCircle, BarChart2, Loader2, Grid3x3, BarChart } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { cn } from "@/lib/utils";
import type { IDockviewPanelProps } from "dockview-react";
import { useOrderFlow } from "@/hooks/useOrderFlow";
import type { FootprintBucket } from "@/hooks/useOrderFlow";

// ─── Types ────────────────────────────────────────────────────────────────────

interface FootprintCell {
  priceLevel: number;
  buyVolume: number;
  sellVolume: number;
}

interface FootprintColumn {
  /** Human-readable time label, e.g. "09:15" */
  time: string;
  cells: FootprintCell[];
  /** Point of Control — price level with highest total volume in this column */
  poc: number;
}

// ─── Constants ────────────────────────────────────────────────────────────────

const SYMBOLS = ["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "RELIANCE", "TCS"];
const INTERVALS: { label: string; minutes: number }[] = [
  { label: "1m", minutes: 1 },
  { label: "3m", minutes: 3 },
  { label: "5m", minutes: 5 },
];

// Canvas drawing constants
const MARGIN_RIGHT = 56;
const MARGIN_LEFT = 12;
const MARGIN_TOP = 8;
const MARGIN_BOTTOM = 24;

// Colour tokens (match FlintTrade CSS custom props where applicable)
const COLOR_BUY = "#22c55e";        // green-500 — buy / bid bars
const COLOR_SELL = "#ef4444";       // red-500  — sell / ask bars
const COLOR_BUY_DIM = "#166534";    // green-900 — dimmer buy fill
const COLOR_SELL_DIM = "#7f1d1d";   // red-900   — dimmer sell fill
const COLOR_POC_BORDER = "#f59e0b"; // amber-400  — POC highlight
const COLOR_GRID = "#2a2a3a";       // border-default equivalent
const COLOR_TEXT = "#a1a1aa";       // text-muted equivalent
const COLOR_TEXT_PRICE = "#e4e4e7"; // text-primary equivalent
const COLOR_LTP_LINE = "#6366f1";   // indigo-500 — LTP dashed line
const COLOR_CANVAS_BG = "#0a0a0f"; // app background

// ─── Backend → Widget data conversion ────────────────────────────────────────

/**
 * Converts backend FootprintBucket[] (keyed cells) into the widget's
 * internal FootprintColumn[] format (array-based cells with priceLevel).
 */
function bucketsToColumns(buckets: FootprintBucket[]): FootprintColumn[] {
  return buckets.map((bucket) => {
    const cells: FootprintCell[] = Object.entries(bucket.cells).map(
      ([priceStr, cell]) => ({
        priceLevel: Number(priceStr),
        buyVolume: cell.buy_volume,
        sellVolume: cell.sell_volume,
      }),
    );
    // Sort cells by price ascending for consistent rendering
    cells.sort((a, b) => a.priceLevel - b.priceLevel);

    return {
      time: bucket.time_label,
      cells,
      poc: bucket.poc_price,
    };
  });
}

// ─── Drawing helpers ──────────────────────────────────────────────────────────

/** Returns the current LTP (mid of last column's POC price range). */
function getLtp(columns: FootprintColumn[]): number {
  if (columns.length === 0) return 0;
  return columns[columns.length - 1].poc;
}

/**
 * Draws the entire footprint chart onto the canvas.
 * All coordinates are in physical (DPR-scaled) pixels.
 */
function drawFootprint(
  ctx: CanvasRenderingContext2D,
  columns: FootprintColumn[],
  physicalWidth: number,
  physicalHeight: number,
  dpr: number,
): void {
  // Clear
  ctx.fillStyle = COLOR_CANVAS_BG;
  ctx.fillRect(0, 0, physicalWidth, physicalHeight);

  if (columns.length === 0) return;

  const css = (px: number) => px * dpr;

  const chartLeft = css(MARGIN_LEFT);
  const chartRight = physicalWidth - css(MARGIN_RIGHT);
  const chartTop = css(MARGIN_TOP);
  const chartBottom = physicalHeight - css(MARGIN_BOTTOM);
  const chartWidth = chartRight - chartLeft;
  const chartHeight = chartBottom - chartTop;

  if (chartWidth <= 0 || chartHeight <= 0) return;

  // Collect all price levels across all columns (sorted ascending)
  const priceSet = new Set<number>();
  columns.forEach((col) => col.cells.forEach((cell) => priceSet.add(cell.priceLevel)));
  const priceLevels = [...priceSet].sort((a, b) => a - b);
  const numLevels = priceLevels.length;
  if (numLevels === 0) return;

  const priceIndex = new Map<number, number>(
    priceLevels.map((p, i) => [p, i]),
  );

  const rowH = chartHeight / numLevels;
  const colW = chartWidth / columns.length;

  // Max volume across all cells — used for bar width scaling
  let maxVol = 1;
  columns.forEach((col) =>
    col.cells.forEach((cell) => {
      maxVol = Math.max(maxVol, cell.buyVolume, cell.sellVolume);
    }),
  );

  // ─── Grid lines (horizontal, per price level) ──────────────────────────────
  ctx.save();
  ctx.strokeStyle = COLOR_GRID;
  ctx.lineWidth = 0.5;
  priceLevels.forEach((_, i) => {
    const y = chartBottom - i * rowH;
    ctx.beginPath();
    ctx.moveTo(chartLeft, y);
    ctx.lineTo(chartRight, y);
    ctx.stroke();
  });
  ctx.restore();

  // ─── Columns ───────────────────────────────────────────────────────────────
  columns.forEach((col, colIdx) => {
    const colLeft = chartLeft + colIdx * colW;
    const colMid = colLeft + colW / 2;

    col.cells.forEach((cell) => {
      const rowIdx = priceIndex.get(cell.priceLevel) ?? 0;
      const cellBottom = chartBottom - rowIdx * rowH;
      const cellTop = cellBottom - rowH;
      const isPoc = cell.priceLevel === col.poc;

      // POC highlight: fill entire cell row in amber tint
      if (isPoc) {
        ctx.save();
        ctx.globalAlpha = 0.12;
        ctx.fillStyle = COLOR_POC_BORDER;
        ctx.fillRect(colLeft, cellTop, colW, rowH);
        ctx.restore();
      }

      // Buy bar (right-facing green, from midpoint rightward)
      const buyBarW = (cell.buyVolume / maxVol) * (colW / 2 - 2);
      if (buyBarW > 0) {
        ctx.fillStyle = isPoc ? COLOR_BUY : COLOR_BUY_DIM;
        ctx.fillRect(colMid + 1, cellTop + 1, buyBarW, rowH - 2);
      }

      // Sell bar (left-facing red, from midpoint leftward)
      const sellBarW = (cell.sellVolume / maxVol) * (colW / 2 - 2);
      if (sellBarW > 0) {
        ctx.fillStyle = isPoc ? COLOR_SELL : COLOR_SELL_DIM;
        ctx.fillRect(colMid - sellBarW - 1, cellTop + 1, sellBarW, rowH - 2);
      }

      // POC border — amber outline around the whole cell
      if (isPoc) {
        ctx.save();
        ctx.strokeStyle = COLOR_POC_BORDER;
        ctx.lineWidth = dpr;
        ctx.strokeRect(colLeft + 0.5, cellTop + 0.5, colW - 1, rowH - 1);
        ctx.restore();
      }
    });

    // Time label at bottom
    ctx.save();
    ctx.fillStyle = COLOR_TEXT;
    ctx.font = `${css(9)}px "JetBrains Mono", monospace`;
    ctx.textAlign = "center";
    ctx.textBaseline = "top";
    ctx.fillText(col.time, colMid, chartBottom + css(4));
    ctx.restore();

    // Column divider
    ctx.save();
    ctx.strokeStyle = COLOR_GRID;
    ctx.lineWidth = dpr;
    ctx.beginPath();
    ctx.moveTo(colLeft, chartTop);
    ctx.lineTo(colLeft, chartBottom);
    ctx.stroke();
    ctx.restore();
  });

  // ─── Price scale (right margin) ────────────────────────────────────────────
  ctx.save();
  ctx.fillStyle = COLOR_TEXT_PRICE;
  ctx.font = `${css(9)}px "JetBrains Mono", monospace`;
  ctx.textAlign = "left";
  ctx.textBaseline = "middle";

  // Show every Nth label to avoid overcrowding
  const maxLabels = Math.floor(chartHeight / css(16));
  const step = Math.max(1, Math.ceil(numLevels / maxLabels));

  priceLevels.forEach((price, i) => {
    if (i % step !== 0) return;
    const y = chartBottom - i * rowH - rowH / 2;
    ctx.fillText(price.toLocaleString("en-IN"), chartRight + css(4), y);
  });
  ctx.restore();

  // ─── LTP dashed line ───────────────────────────────────────────────────────
  const ltp = getLtp(columns);
  const ltpIdx = priceIndex.get(ltp);
  if (ltpIdx !== undefined) {
    const ltpY = chartBottom - ltpIdx * rowH - rowH / 2;
    ctx.save();
    ctx.strokeStyle = COLOR_LTP_LINE;
    ctx.lineWidth = dpr;
    ctx.setLineDash([css(4), css(3)]);
    ctx.beginPath();
    ctx.moveTo(chartLeft, ltpY);
    ctx.lineTo(chartRight, ltpY);
    ctx.stroke();
    ctx.restore();
  }
}

// ─── Heatmap color helpers ───────────────────────────────────────────────────

interface RGB { r: number; g: number; b: number }

const HEATMAP_BUY_RAMP: RGB[] = [
  { r: 10, g: 15, b: 30 },
  { r: 15, g: 60, b: 100 },
  { r: 30, g: 120, b: 180 },
  { r: 60, g: 200, b: 230 },
  { r: 200, g: 250, b: 255 },
];

const HEATMAP_SELL_RAMP: RGB[] = [
  { r: 30, g: 10, b: 10 },
  { r: 100, g: 30, b: 15 },
  { r: 180, g: 60, b: 30 },
  { r: 230, g: 150, b: 60 },
  { r: 255, g: 230, b: 180 },
];

function lerpRGB(a: RGB, b: RGB, t: number): RGB {
  return {
    r: Math.round(a.r + (b.r - a.r) * t),
    g: Math.round(a.g + (b.g - a.g) * t),
    b: Math.round(a.b + (b.b - a.b) * t),
  };
}

function colorFromRamp(ramp: RGB[], intensity: number): string {
  const clamped = Math.max(0, Math.min(1, intensity));
  const segments = ramp.length - 1;
  const pos = clamped * segments;
  const idx = Math.min(Math.floor(pos), segments - 1);
  const frac = pos - idx;
  const c = lerpRGB(ramp[idx], ramp[idx + 1], frac);
  return `rgb(${c.r},${c.g},${c.b})`;
}

/**
 * Draws the footprint data as a heatmap: each cell is colored by volume
 * intensity. Buy-dominant cells in blue/cyan, sell-dominant in red/orange.
 */
function drawFootprintHeatmap(
  ctx: CanvasRenderingContext2D,
  columns: FootprintColumn[],
  physicalWidth: number,
  physicalHeight: number,
  dpr: number,
): void {
  ctx.fillStyle = COLOR_CANVAS_BG;
  ctx.fillRect(0, 0, physicalWidth, physicalHeight);

  if (columns.length === 0) return;

  const css = (px: number) => px * dpr;

  const chartLeft = css(MARGIN_LEFT);
  const chartRight = physicalWidth - css(MARGIN_RIGHT);
  const chartTop = css(MARGIN_TOP);
  const chartBottom = physicalHeight - css(MARGIN_BOTTOM);
  const chartWidth = chartRight - chartLeft;
  const chartHeight = chartBottom - chartTop;

  if (chartWidth <= 0 || chartHeight <= 0) return;

  const priceSet = new Set<number>();
  columns.forEach((col) => col.cells.forEach((cell) => priceSet.add(cell.priceLevel)));
  const priceLevels = [...priceSet].sort((a, b) => a - b);
  const numLevels = priceLevels.length;
  if (numLevels === 0) return;

  const priceIndex = new Map<number, number>(priceLevels.map((p, i) => [p, i]));
  const rowH = chartHeight / numLevels;
  const colW = chartWidth / columns.length;

  let maxVol = 1;
  columns.forEach((col) =>
    col.cells.forEach((cell) => {
      maxVol = Math.max(maxVol, cell.buyVolume, cell.sellVolume);
    }),
  );

  const gamma = 0.5;

  // Draw heatmap cells
  columns.forEach((col, colIdx) => {
    const colLeft = chartLeft + colIdx * colW;

    col.cells.forEach((cell) => {
      const rowIdx = priceIndex.get(cell.priceLevel) ?? 0;
      const cellBottom = chartBottom - rowIdx * rowH;
      const cellTop = cellBottom - rowH;
      const totalVol = cell.buyVolume + cell.sellVolume;
      if (totalVol === 0) return;

      const dominantBuy = cell.buyVolume >= cell.sellVolume;
      const dominantVol = dominantBuy ? cell.buyVolume : cell.sellVolume;
      const intensity = Math.pow(dominantVol / maxVol, gamma);

      ctx.fillStyle = colorFromRamp(
        dominantBuy ? HEATMAP_BUY_RAMP : HEATMAP_SELL_RAMP,
        intensity,
      );
      ctx.fillRect(colLeft, cellTop, Math.ceil(colW) + 1, Math.ceil(rowH) + 1);

      // POC highlight
      if (cell.priceLevel === col.poc) {
        ctx.save();
        ctx.strokeStyle = COLOR_POC_BORDER;
        ctx.lineWidth = dpr;
        ctx.strokeRect(colLeft + 0.5, cellTop + 0.5, colW - 1, rowH - 1);
        ctx.restore();
      }
    });

    // Time label
    ctx.save();
    ctx.fillStyle = COLOR_TEXT;
    ctx.font = `${css(9)}px "JetBrains Mono", monospace`;
    ctx.textAlign = "center";
    ctx.textBaseline = "top";
    ctx.fillText(col.time, colLeft + colW / 2, chartBottom + css(4));
    ctx.restore();
  });

  // Price scale
  ctx.save();
  ctx.fillStyle = COLOR_TEXT_PRICE;
  ctx.font = `${css(9)}px "JetBrains Mono", monospace`;
  ctx.textAlign = "left";
  ctx.textBaseline = "middle";
  const maxLabels = Math.floor(chartHeight / css(16));
  const step = Math.max(1, Math.ceil(numLevels / maxLabels));
  priceLevels.forEach((price, i) => {
    if (i % step !== 0) return;
    const y = chartBottom - i * rowH - rowH / 2;
    ctx.fillText(price.toLocaleString("en-IN"), chartRight + css(4), y);
  });
  ctx.restore();

  // LTP line
  const ltp = getLtp(columns);
  const ltpIdx = priceIndex.get(ltp);
  if (ltpIdx !== undefined) {
    const ltpY = chartBottom - ltpIdx * rowH - rowH / 2;
    ctx.save();
    ctx.strokeStyle = COLOR_LTP_LINE;
    ctx.lineWidth = dpr;
    ctx.setLineDash([css(4), css(3)]);
    ctx.beginPath();
    ctx.moveTo(chartLeft, ltpY);
    ctx.lineTo(chartRight, ltpY);
    ctx.stroke();
    ctx.restore();
  }
}

// ─── View mode type ──────────────────────────────────────────────────────────

type ViewMode = "footprint" | "heatmap";

// ─── Main widget ──────────────────────────────────────────────────────────────

function OrderFlowWidget(_props: IDockviewPanelProps) {
  const [symbol, setSymbol] = useState("NIFTY");
  const [intervalLabel, setIntervalLabel] = useState("5m");
  const [viewMode, setViewMode] = useState<ViewMode>("footprint");

  const intervalMinutes = useMemo(
    () => INTERVALS.find((i) => i.label === intervalLabel)?.minutes ?? 5,
    [intervalLabel],
  );

  // Fetch footprint data from backend (interval in seconds for the API)
  const { data, isLoading, isError, error } = useOrderFlow(
    symbol,
    "NSE",
    intervalMinutes * 60,
  );

  const columns = useMemo(
    () => (data?.buckets ? bucketsToColumns(data.buckets) : []),
    [data],
  );

  const ltp = useMemo(() => getLtp(columns), [columns]);

  const canvasRef = useRef<HTMLCanvasElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const rafRef = useRef<number | null>(null);
  const sizeRef = useRef({ width: 0, height: 0 });
  const columnsRef = useRef(columns);
  columnsRef.current = columns;
  const viewModeRef = useRef(viewMode);
  viewModeRef.current = viewMode;

  // Paint function — schedules via rAF to prevent redundant repaints
  // Uses refs to always read the latest state without re-creating the callback.
  const paint = useCallback(() => {
    if (rafRef.current !== null) return;
    rafRef.current = requestAnimationFrame(() => {
      rafRef.current = null;
      const canvas = canvasRef.current;
      if (!canvas) return;
      const ctx = canvas.getContext("2d");
      if (!ctx) return;
      const dpr = window.devicePixelRatio || 1;
      const drawFn = viewModeRef.current === "heatmap" ? drawFootprintHeatmap : drawFootprint;
      drawFn(ctx, columnsRef.current, canvas.width, canvas.height, dpr);
    });
  }, []);

  // ResizeObserver: keep canvas size in sync with container, respecting DPR
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
        return; // no meaningful size change
      }
      sizeRef.current = { width, height };
      const canvas = canvasRef.current;
      if (!canvas) return;
      const dpr = window.devicePixelRatio || 1;
      canvas.width = Math.floor(width * dpr);
      canvas.height = Math.floor(height * dpr);
      canvas.style.width = `${width}px`;
      canvas.style.height = `${height}px`;
      paint();
    });

    observer.observe(container);
    return () => observer.disconnect();
  }, [paint]);

  // Repaint when columns or view mode change
  useEffect(() => {
    paint();
  }, [columns, viewMode, paint]);

  // Cleanup rAF on unmount
  useEffect(() => {
    return () => {
      if (rafRef.current !== null) {
        cancelAnimationFrame(rafRef.current);
      }
    };
  }, []);

  return (
    <div className="flex flex-col h-full bg-surface-base select-none">
      {/* ─── Toolbar ────────────────────────────────────────────────────── */}
      <div className="flex items-center gap-2 px-3 py-1.5 border-b border-border-default shrink-0">
        {/* Symbol selector */}
        <span className="sr-only" id="of-symbol-label">
          Symbol
        </span>
        <Select value={symbol} onValueChange={setSymbol}>
          <SelectTrigger
            className="h-6 w-28 text-xs border-border-default bg-surface-card text-text-primary focus:ring-0"
            aria-labelledby="of-symbol-label"
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

        {/* Interval selector */}
        <span className="sr-only" id="of-interval-label">
          Interval
        </span>
        <div className="flex items-center gap-0.5" role="group" aria-labelledby="of-interval-label">
          {INTERVALS.map((iv) => (
            <button
              key={iv.label}
              type="button"
              onClick={() => setIntervalLabel(iv.label)}
              className={cn(
                "h-6 px-2 text-xs rounded font-mono transition-colors",
                intervalLabel === iv.label
                  ? "bg-surface-active text-text-primary"
                  : "text-text-muted hover:text-text-secondary hover:bg-surface-hover",
              )}
              aria-pressed={intervalLabel === iv.label}
              aria-label={`${iv.label} interval`}
            >
              {iv.label}
            </button>
          ))}
        </div>

        {/* View mode toggle */}
        <div className="flex items-center gap-0.5 border-l border-border-default pl-2 ml-1" role="group" aria-label="View mode">
          <button
            type="button"
            onClick={() => setViewMode("footprint")}
            className={cn(
              "h-6 px-1.5 rounded transition-colors flex items-center gap-1",
              viewMode === "footprint"
                ? "bg-surface-active text-text-primary"
                : "text-text-muted hover:text-text-secondary hover:bg-surface-hover",
            )}
            aria-pressed={viewMode === "footprint"}
            aria-label="Footprint view"
          >
            <BarChart className="size-3" aria-hidden="true" />
            <span className="text-xs">Footprint</span>
          </button>
          <button
            type="button"
            onClick={() => setViewMode("heatmap")}
            className={cn(
              "h-6 px-1.5 rounded transition-colors flex items-center gap-1",
              viewMode === "heatmap"
                ? "bg-surface-active text-text-primary"
                : "text-text-muted hover:text-text-secondary hover:bg-surface-hover",
            )}
            aria-pressed={viewMode === "heatmap"}
            aria-label="Heatmap view"
          >
            <Grid3x3 className="size-3" aria-hidden="true" />
            <span className="text-xs">Heatmap</span>
          </button>
        </div>

        {/* LTP display */}
        <div className="ml-auto flex items-center gap-1.5">
          <span className="text-xs text-text-muted">LTP</span>
          <span className="font-mono text-xs font-semibold text-accent tabular-nums">
            {ltp > 0 ? ltp.toLocaleString("en-IN") : "—"}
          </span>
        </div>

        {/* Status badge */}
        {isLoading && (
          <Badge
            variant="outline"
            className="text-xs border-blue-500/40 text-blue-400 bg-blue-500/10 h-5 px-1.5"
            aria-label="Loading order flow data"
          >
            <Loader2 className="size-2.5 mr-1 animate-spin" aria-hidden="true" />
            Loading
          </Badge>
        )}
        {isError && (
          <Badge
            variant="outline"
            className="text-xs border-red-500/40 text-red-400 bg-red-500/10 h-5 px-1.5"
            aria-label={`Error loading data: ${error instanceof Error ? error.message : "Unknown error"}`}
          >
            <AlertCircle className="size-2.5 mr-1" aria-hidden="true" />
            Error
          </Badge>
        )}
        {!isLoading && !isError && columns.length > 0 && (
          <Badge
            variant="outline"
            className="text-xs border-amber-500/40 text-amber-400 bg-amber-500/10 h-5 px-1.5"
            aria-label="Displaying synthetic data from backend — live tick data requires WebSocket"
          >
            <AlertCircle className="size-2.5 mr-1" aria-hidden="true" />
            Synthetic
          </Badge>
        )}
      </div>

      {/* ─── Legend ─────────────────────────────────────────────────────── */}
      <div className="flex items-center gap-3 px-3 py-1 border-b border-border-default shrink-0">
        <div className="flex items-center gap-1">
          <div className="w-3 h-2 rounded-sm bg-profit" aria-hidden="true" />
          <span className="text-xs text-text-muted">Buy</span>
        </div>
        <div className="flex items-center gap-1">
          <div className="w-3 h-2 rounded-sm bg-loss" aria-hidden="true" />
          <span className="text-xs text-text-muted">Sell</span>
        </div>
        <div className="flex items-center gap-1">
          <div className="w-3 h-2 rounded-sm border border-amber-400" aria-hidden="true" />
          <span className="text-xs text-zinc-500">POC</span>
        </div>
        <div className="flex items-center gap-1">
          <div
            className="w-3 border-t border-dashed border-indigo-400"
            aria-hidden="true"
          />
          <span className="text-xs text-zinc-500">LTP</span>
        </div>
        <div className="ml-auto text-xs text-text-muted">
          {columns.length} bars &bull; {symbol} {intervalLabel}
        </div>
      </div>

      {/* ─── Chart canvas ────────────────────────────────────────────────── */}
      <div
        ref={containerRef}
        className="flex-1 relative min-h-0"
        role="img"
        aria-label={`Order flow footprint chart for ${symbol}, ${intervalLabel} interval. Shows buy volume (green) and sell volume (red) per price level per time bucket. Point of Control (POC) highlighted in amber.`}
      >
        <canvas
          ref={canvasRef}
          className="absolute inset-0 block"
          aria-hidden="true"
        />
        {isLoading && columns.length === 0 && (
          <div className="absolute inset-0 flex flex-col items-center justify-center gap-3">
            <Skeleton className="h-3 w-48" />
            <Skeleton className="h-3 w-36" />
            <Skeleton className="h-3 w-40" />
            <span className="text-xs text-text-muted mt-1">Loading order flow data...</span>
          </div>
        )}
        {isError && (
          <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 text-loss/70">
            <AlertCircle className="size-8" aria-hidden="true" />
            <span className="text-sm">
              {error instanceof Error ? error.message : "Failed to load data"}
            </span>
            <span className="text-xs text-text-muted">Retrying automatically...</span>
          </div>
        )}
        {!isLoading && !isError && columns.length === 0 && (
          <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 text-text-muted">
            <BarChart2 className="size-8" aria-hidden="true" />
            <span className="text-sm">No data</span>
          </div>
        )}
      </div>
    </div>
  );
}

export default memo(OrderFlowWidget);
