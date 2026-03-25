/**
 * OrderFlowWidget — Order Flow Footprint chart for FlintTrade terminal.
 *
 * Visualises order flow as a footprint chart using Canvas2D (NOT SVG, NOT DOM).
 * Each column = one time bucket. Each row within a column = a price level.
 * Bid (buy) volume extends right as a green bar. Ask (sell) volume extends
 * left as a red bar. The POC (Point of Control — highest total volume) is
 * highlighted per column with a yellow border.
 *
 * Since no backend order flow aggregator exists yet (planned for v0.3):
 *   - Deterministic sample data is generated to demonstrate the full UI.
 *   - A "Sample Data" badge is shown in the header.
 *   - When live data becomes available, replace generateSampleData() with
 *     a TanStack Query hook that calls the FlintTrade backend endpoint.
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
} from "react";
import { AlertCircle, BarChart2 } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { cn } from "@/lib/utils";
import type { IDockviewPanelProps } from "dockview-react";

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

// ─── Sample data generation ────────────────────────────────────────────────────

/**
 * Generates deterministic sample footprint data for demonstration.
 * Returns columns ordered oldest → newest (left → right on chart).
 *
 * @param symbol   - used to seed price range so different symbols look different
 * @param interval - column interval in minutes
 * @param cols     - number of time columns to generate
 */
function generateSampleData(
  symbol: string,
  interval: number,
  cols = 20,
): FootprintColumn[] {
  // Seed from symbol to get different base prices per symbol
  const basePrice =
    symbol === "NIFTY"
      ? 22_500
      : symbol === "BANKNIFTY"
        ? 48_000
        : symbol === "FINNIFTY"
          ? 21_000
          : symbol === "MIDCPNIFTY"
            ? 11_500
            : symbol === "RELIANCE"
              ? 2_900
              : 3_800; // TCS

  const tickSize = basePrice >= 10_000 ? 50 : basePrice >= 1_000 ? 5 : 1;
  const priceRows = 10; // number of price levels per column

  // Simple PRNG seeded by symbol+interval so data is stable across renders
  let seed = symbol.split("").reduce((a, c) => a + c.charCodeAt(0), interval);
  function rand(): number {
    seed = (seed * 1664525 + 1013904223) & 0xffff_ffff;
    return Math.abs(seed) / 0x7fff_ffff;
  }

  // Generate a random walk for mid-price across columns
  let mid = basePrice;
  const columns: FootprintColumn[] = [];

  // Work backwards from "now" to produce time labels
  const now = new Date();
  now.setSeconds(0, 0);

  for (let c = 0; c < cols; c++) {
    const colTime = new Date(now.getTime() - (cols - 1 - c) * interval * 60_000);
    const timeLabel = colTime.toLocaleTimeString("en-IN", {
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
    });

    // Drift mid-price randomly
    mid += (rand() - 0.5) * tickSize * 4;
    mid = Math.round(mid / tickSize) * tickSize;

    // Build cells around mid
    const startPrice = mid - Math.floor(priceRows / 2) * tickSize;
    const cells: FootprintCell[] = [];

    for (let r = 0; r < priceRows; r++) {
      const priceLevel = startPrice + r * tickSize;
      // More volume near mid — Gaussian-ish distribution
      const dist = Math.abs(r - priceRows / 2) / (priceRows / 2);
      const volumeScale = Math.max(0.1, 1 - dist * 0.8) * 10_000;
      const buyVolume = Math.round(rand() * volumeScale * (1 + rand() * 0.5));
      const sellVolume = Math.round(rand() * volumeScale * (1 + rand() * 0.5));
      cells.push({ priceLevel, buyVolume, sellVolume });
    }

    // POC = price level with max (buy + sell) volume
    const poc = cells.reduce(
      (best, cell) =>
        cell.buyVolume + cell.sellVolume > best.buyVolume + best.sellVolume
          ? cell
          : best,
      cells[0],
    ).priceLevel;

    columns.push({ time: timeLabel, cells, poc });
  }

  return columns;
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

// ─── Main widget ──────────────────────────────────────────────────────────────

export default function OrderFlowWidget(_props: IDockviewPanelProps) {
  const [symbol, setSymbol] = useState("NIFTY");
  const [intervalLabel, setIntervalLabel] = useState("5m");

  const intervalMinutes = useMemo(
    () => INTERVALS.find((i) => i.label === intervalLabel)?.minutes ?? 5,
    [intervalLabel],
  );

  const columns = useMemo(
    () => generateSampleData(symbol, intervalMinutes, 20),
    [symbol, intervalMinutes],
  );

  const ltp = useMemo(() => getLtp(columns), [columns]);

  const canvasRef = useRef<HTMLCanvasElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const rafRef = useRef<number | null>(null);
  const sizeRef = useRef({ width: 0, height: 0 });
  const columnsRef = useRef(columns);
  columnsRef.current = columns;

  // Paint function — schedules via rAF to prevent redundant repaints
  // Uses columnsRef to always read the latest columns without re-creating the callback.
  const paint = useCallback(() => {
    if (rafRef.current !== null) return;
    rafRef.current = requestAnimationFrame(() => {
      rafRef.current = null;
      const canvas = canvasRef.current;
      if (!canvas) return;
      const ctx = canvas.getContext("2d");
      if (!ctx) return;
      drawFootprint(ctx, columnsRef.current, canvas.width, canvas.height, window.devicePixelRatio || 1);
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

  // Repaint when columns change (symbol/interval change)
  useEffect(() => {
    paint();
  }, [columns, paint]);

  // Cleanup rAF on unmount
  useEffect(() => {
    return () => {
      if (rafRef.current !== null) {
        cancelAnimationFrame(rafRef.current);
      }
    };
  }, []);

  return (
    <div className="flex flex-col h-full bg-[#0a0a0f] select-none">
      {/* ─── Toolbar ────────────────────────────────────────────────────── */}
      <div className="flex items-center gap-2 px-3 py-1.5 border-b border-[#2a2a3a] shrink-0">
        {/* Symbol selector */}
        <span className="sr-only" id="of-symbol-label">
          Symbol
        </span>
        <Select value={symbol} onValueChange={setSymbol}>
          <SelectTrigger
            className="h-6 w-28 text-xs border-[#2a2a3a] bg-[#16161f] text-zinc-200 focus:ring-0"
            aria-labelledby="of-symbol-label"
          >
            <SelectValue />
          </SelectTrigger>
          <SelectContent className="bg-[#16161f] border-[#2a2a3a]">
            {SYMBOLS.map((s) => (
              <SelectItem
                key={s}
                value={s}
                className="text-xs text-zinc-200 focus:bg-[#2a2a3a]"
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
                  ? "bg-[#2a2a3a] text-zinc-100"
                  : "text-zinc-500 hover:text-zinc-300 hover:bg-[#1a1a2a]",
              )}
              aria-pressed={intervalLabel === iv.label}
              aria-label={`${iv.label} interval`}
            >
              {iv.label}
            </button>
          ))}
        </div>

        {/* LTP display */}
        <div className="ml-auto flex items-center gap-1.5">
          <span className="text-xs text-zinc-500">LTP</span>
          <span className="font-mono text-xs font-semibold text-indigo-400 tabular-nums">
            {ltp > 0 ? ltp.toLocaleString("en-IN") : "—"}
          </span>
        </div>

        {/* Sample data badge */}
        <Badge
          variant="outline"
          className="text-xs border-amber-500/40 text-amber-400 bg-amber-500/10 h-5 px-1.5"
          aria-label="Displaying sample data — live data requires backend order flow aggregator"
        >
          <AlertCircle className="size-2.5 mr-1" aria-hidden="true" />
          Sample Data
        </Badge>
      </div>

      {/* ─── Legend ─────────────────────────────────────────────────────── */}
      <div className="flex items-center gap-3 px-3 py-1 border-b border-[#2a2a3a] shrink-0">
        <div className="flex items-center gap-1">
          <div className="w-3 h-2 rounded-sm bg-[#22c55e]" aria-hidden="true" />
          <span className="text-xs text-zinc-500">Buy</span>
        </div>
        <div className="flex items-center gap-1">
          <div className="w-3 h-2 rounded-sm bg-[#ef4444]" aria-hidden="true" />
          <span className="text-xs text-zinc-500">Sell</span>
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
        <div className="ml-auto text-xs text-zinc-600">
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
        {columns.length === 0 && (
          <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 text-zinc-600">
            <BarChart2 className="size-8" aria-hidden="true" />
            <span className="text-sm">No data</span>
          </div>
        )}
      </div>
    </div>
  );
}
