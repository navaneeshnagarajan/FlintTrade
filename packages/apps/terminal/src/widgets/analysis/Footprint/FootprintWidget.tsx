/**
 * FootprintWidget — Dedicated footprint chart for FlintTrade terminal.
 *
 * Distinct from OrderFlowWidget (which bundles both footprint and heatmap view
 * modes). This widget renders a single, rich footprint chart where each cell
 * shows buy volume (green bar), sell volume (red bar), and the delta value
 * (buy − sell) as a number, colour-coded green/red by sign.
 *
 * Canvas layout:
 *   Y-axis: price levels (ascending, lowest at bottom)
 *   X-axis: time buckets (oldest left, newest right)
 *   Each cell = one time bucket × one price level
 *   Bars: bid bar grows rightward from cell mid, ask bar grows leftward
 *   Delta text: centred in cell, green if positive, red if negative
 *   POC row: amber border + subtle amber fill per column
 *   Cumulative delta strip: below the main chart, line chart of running delta
 *
 * Performance:
 *   Single canvas, rAF-gated repaints, ResizeObserver for DPR-aware sizing.
 *
 * Accessibility:
 *   role="img" on container with descriptive aria-label.
 *   Symbol and interval selectors labelled via sr-only spans.
 */

import {
  useRef,
  useEffect,
  useState,
  useMemo,
  useCallback,
  memo,
} from "react";
import { AlertCircle, BarChart, Loader2 } from "lucide-react";
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
import { resolveOrderFlowExchange } from "../orderFlowExchange";

// ─── Types ────────────────────────────────────────────────────────────────────

interface FPCell {
  priceLevel: number;
  buyVolume: number;
  sellVolume: number;
  delta: number;
}

interface FPColumn {
  time: string;
  cells: FPCell[];
  poc: number;
  totalDelta: number;
}

// ─── Constants ────────────────────────────────────────────────────────────────

const SYMBOLS = [
  "NIFTY",
  "BANKNIFTY",
  "FINNIFTY",
  "MIDCPNIFTY",
  "RELIANCE",
  "TCS",
];
const INTERVALS: { label: string; minutes: number }[] = [
  { label: "1m", minutes: 1 },
  { label: "3m", minutes: 3 },
  { label: "5m", minutes: 5 },
];

function formatIntervalLabel(seconds: number | undefined, fallback: string): string {
  if (seconds === undefined || !Number.isFinite(seconds) || seconds <= 0) return fallback;
  return seconds % 60 === 0 ? `${seconds / 60}m` : `${seconds}s`;
}

// Layout margins (CSS px)
const MARGIN_RIGHT = 60;
const MARGIN_LEFT = 8;
const MARGIN_TOP = 8;
const MARGIN_BOTTOM_CHART = 4;   // gap between chart and delta strip
const DELTA_STRIP_H = 56;        // CSS px height reserved for cumulative delta
const MARGIN_BOTTOM_DELTA = 20;  // time labels below delta strip

// Canvas colours
const C_BG = "#0a0a0f";
const C_BUY = "#22c55e";
const C_BUY_DIM = "#166534";
const C_SELL = "#ef4444";
const C_SELL_DIM = "#7f1d1d";
const C_POC = "#f59e0b";
const C_GRID = "#2a2a3a";
const C_TEXT = "#a1a1aa";
const C_TEXT_PRICE = "#e4e4e7";
const C_LTP = "#6366f1";
const C_DELTA_POS = "#22c55e";
const C_DELTA_NEG = "#ef4444";
const C_DELTA_LINE = "#818cf8"; // indigo-400

// ─── Data conversion ──────────────────────────────────────────────────────────

function bucketsToColumns(buckets: FootprintBucket[]): FPColumn[] {
  const grouped = new Map<string, FPColumn>();

  for (const b of buckets) {
    if (!grouped.has(b.time_label)) {
      grouped.set(b.time_label, {
        time: b.time_label,
        cells: [],
        poc: b.poc_price,
        totalDelta: 0,
      });
    }
    const col = grouped.get(b.time_label)!;
    for (const [priceStr, cell] of Object.entries(b.cells)) {
      const delta = cell.buy_volume - cell.sell_volume;
      col.cells.push({
        priceLevel: Number(priceStr),
        buyVolume: cell.buy_volume,
        sellVolume: cell.sell_volume,
        delta,
      });
      col.totalDelta += delta;
    }
  }

  // Sort columns chronologically, cells price-ascending
  const cols = [...grouped.values()];
  for (const col of cols) {
    col.cells.sort((a, b) => a.priceLevel - b.priceLevel);
  }
  return cols;
}

// ─── Cumulative delta across columns ─────────────────────────────────────────

function cumulativeDelta(columns: FPColumn[]): number[] {
  let running = 0;
  return columns.map((col) => {
    running += col.totalDelta;
    return running;
  });
}

// ─── Drawing ──────────────────────────────────────────────────────────────────

function drawFootprint(
  ctx: CanvasRenderingContext2D,
  columns: FPColumn[],
  cumDelta: number[],
  physW: number,
  physH: number,
  dpr: number,
): void {
  const css = (px: number) => px * dpr;

  ctx.fillStyle = C_BG;
  ctx.fillRect(0, 0, physW, physH);

  if (columns.length === 0) return;

  // Layout zones
  const chartLeft = css(MARGIN_LEFT);
  const chartRight = physW - css(MARGIN_RIGHT);
  const chartTop = css(MARGIN_TOP);
  const deltaStripTop = physH - css(MARGIN_BOTTOM_DELTA) - css(DELTA_STRIP_H);
  const chartBottom = deltaStripTop - css(MARGIN_BOTTOM_CHART);

  const chartW = chartRight - chartLeft;
  const chartH = chartBottom - chartTop;
  const deltaStripH = css(DELTA_STRIP_H);

  if (chartW <= 0 || chartH <= 0) return;

  // Collect all price levels
  const priceSet = new Set<number>();
  for (const col of columns) {
    for (const cell of col.cells) priceSet.add(cell.priceLevel);
  }
  const priceLevels = [...priceSet].sort((a, b) => a - b);
  const numLevels = priceLevels.length;
  if (numLevels === 0) return;

  const priceIdx = new Map(priceLevels.map((p, i) => [p, i]));
  const rowH = chartH / numLevels;
  const colW = chartW / columns.length;

  let maxVol = 1;
  for (const col of columns) {
    for (const cell of col.cells) {
      maxVol = Math.max(maxVol, cell.buyVolume, cell.sellVolume);
    }
  }

  // Decide whether to show delta text (only if cells are large enough)
  const showDeltaText = rowH >= css(10) && colW >= css(28);

  // ── Grid lines ────────────────────────────────────────────────────────────
  ctx.save();
  ctx.strokeStyle = C_GRID;
  ctx.lineWidth = 0.5;
  for (let i = 0; i <= numLevels; i++) {
    const y = chartBottom - i * rowH;
    ctx.beginPath();
    ctx.moveTo(chartLeft, y);
    ctx.lineTo(chartRight, y);
    ctx.stroke();
  }
  ctx.restore();

  // ── Columns ───────────────────────────────────────────────────────────────
  for (let colIdx = 0; colIdx < columns.length; colIdx++) {
    const col = columns[colIdx];
    const colLeft = chartLeft + colIdx * colW;
    const colMid = colLeft + colW / 2;

    // Column divider
    ctx.save();
    ctx.strokeStyle = C_GRID;
    ctx.lineWidth = dpr;
    ctx.beginPath();
    ctx.moveTo(colLeft, chartTop);
    ctx.lineTo(colLeft, chartBottom);
    ctx.stroke();
    ctx.restore();

    for (const cell of col.cells) {
      const ri = priceIdx.get(cell.priceLevel) ?? 0;
      const cellBottom = chartBottom - ri * rowH;
      const cellTop = cellBottom - rowH;
      const isPoc = cell.priceLevel === col.poc;

      // POC background
      if (isPoc) {
        ctx.save();
        ctx.globalAlpha = 0.1;
        ctx.fillStyle = C_POC;
        ctx.fillRect(colLeft, cellTop, colW, rowH);
        ctx.globalAlpha = 1;
        ctx.strokeStyle = C_POC;
        ctx.lineWidth = dpr;
        ctx.strokeRect(colLeft + 0.5, cellTop + 0.5, colW - 1, rowH - 1);
        ctx.restore();
      }

      // Buy bar (right of midpoint, green)
      const buyW = (cell.buyVolume / maxVol) * (colW / 2 - 2);
      if (buyW > 0) {
        ctx.fillStyle = isPoc ? C_BUY : C_BUY_DIM;
        ctx.fillRect(colMid + 1, cellTop + 1, buyW, rowH - 2);
      }

      // Sell bar (left of midpoint, red)
      const sellW = (cell.sellVolume / maxVol) * (colW / 2 - 2);
      if (sellW > 0) {
        ctx.fillStyle = isPoc ? C_SELL : C_SELL_DIM;
        ctx.fillRect(colMid - sellW - 1, cellTop + 1, sellW, rowH - 2);
      }

      // Delta text
      if (showDeltaText) {
        const sign = cell.delta >= 0 ? "+" : "";
        const label = `${sign}${cell.delta.toLocaleString("en-IN")}`;
        ctx.save();
        ctx.fillStyle = cell.delta >= 0 ? C_DELTA_POS : C_DELTA_NEG;
        ctx.font = `bold ${css(8)}px "JetBrains Mono", monospace`;
        ctx.textAlign = "center";
        ctx.textBaseline = "middle";
        ctx.fillText(label, colMid, (cellTop + cellBottom) / 2);
        ctx.restore();
      }
    }

    // Time label
    ctx.save();
    ctx.fillStyle = C_TEXT;
    ctx.font = `${css(8)}px "JetBrains Mono", monospace`;
    ctx.textAlign = "center";
    ctx.textBaseline = "top";
    ctx.fillText(col.time, colMid, deltaStripTop + deltaStripH + css(3));
    ctx.restore();
  }

  // ── Price scale ───────────────────────────────────────────────────────────
  ctx.save();
  ctx.fillStyle = C_TEXT_PRICE;
  ctx.font = `${css(9)}px "JetBrains Mono", monospace`;
  ctx.textAlign = "left";
  ctx.textBaseline = "middle";
  const maxLabels = Math.floor(chartH / css(16));
  const labelStep = Math.max(1, Math.ceil(numLevels / maxLabels));
  for (let i = 0; i < numLevels; i += labelStep) {
    const y = chartBottom - i * rowH - rowH / 2;
    ctx.fillText(priceLevels[i].toLocaleString("en-IN"), chartRight + css(4), y);
  }
  ctx.restore();

  // ── LTP dashed line ───────────────────────────────────────────────────────
  if (columns.length > 0) {
    const lastCol = columns[columns.length - 1];
    const ltpIdx = priceIdx.get(lastCol.poc);
    if (ltpIdx !== undefined) {
      const ltpY = chartBottom - ltpIdx * rowH - rowH / 2;
      ctx.save();
      ctx.strokeStyle = C_LTP;
      ctx.lineWidth = dpr;
      ctx.setLineDash([css(4), css(3)]);
      ctx.beginPath();
      ctx.moveTo(chartLeft, ltpY);
      ctx.lineTo(chartRight, ltpY);
      ctx.stroke();
      ctx.restore();
    }
  }

  // ── Cumulative delta strip ────────────────────────────────────────────────
  if (cumDelta.length > 0) {
    const stripLeft = chartLeft;
    const stripRight = chartRight;
    const stripW = stripRight - stripLeft;

    // Divider line
    ctx.save();
    ctx.strokeStyle = C_GRID;
    ctx.lineWidth = dpr;
    ctx.beginPath();
    ctx.moveTo(stripLeft, deltaStripTop);
    ctx.lineTo(stripRight, deltaStripTop);
    ctx.stroke();

    // Zero baseline
    const zeroY = deltaStripTop + deltaStripH / 2;
    ctx.strokeStyle = C_GRID;
    ctx.lineWidth = 0.5;
    ctx.beginPath();
    ctx.moveTo(stripLeft, zeroY);
    ctx.lineTo(stripRight, zeroY);
    ctx.stroke();
    ctx.restore();

    // Label
    ctx.save();
    ctx.fillStyle = C_TEXT;
    ctx.font = `${css(7)}px "JetBrains Mono", monospace`;
    ctx.textAlign = "left";
    ctx.textBaseline = "top";
    ctx.fillText("Cumulative Δ", chartLeft + css(2), deltaStripTop + css(2));
    ctx.restore();

    const minD = Math.min(...cumDelta);
    const maxD = Math.max(...cumDelta);
    const range = Math.max(Math.abs(maxD), Math.abs(minD), 1);

    const segW = stripW / (cumDelta.length - 1 || 1);

    // Fill area under/over baseline
    ctx.save();
    ctx.beginPath();
    ctx.moveTo(stripLeft, zeroY);
    for (let i = 0; i < cumDelta.length; i++) {
      const x = stripLeft + i * segW;
      const norm = cumDelta[i] / range;           // −1 to +1
      const y = zeroY - norm * (deltaStripH / 2 - css(4));
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    }
    ctx.lineTo(stripLeft + (cumDelta.length - 1) * segW, zeroY);
    ctx.closePath();

    const lastD = cumDelta[cumDelta.length - 1];
    ctx.globalAlpha = 0.25;
    ctx.fillStyle = lastD >= 0 ? C_DELTA_POS : C_DELTA_NEG;
    ctx.fill();
    ctx.restore();

    // Line
    ctx.save();
    ctx.strokeStyle = C_DELTA_LINE;
    ctx.lineWidth = dpr * 1.5;
    ctx.lineJoin = "round";
    ctx.beginPath();
    for (let i = 0; i < cumDelta.length; i++) {
      const x = stripLeft + i * segW;
      const norm = cumDelta[i] / range;
      const y = zeroY - norm * (deltaStripH / 2 - css(4));
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    }
    ctx.stroke();
    ctx.restore();

    // Current cumulative delta value label
    const finalDelta = cumDelta[cumDelta.length - 1];
    ctx.save();
    ctx.fillStyle = finalDelta >= 0 ? C_DELTA_POS : C_DELTA_NEG;
    ctx.font = `bold ${css(8)}px "JetBrains Mono", monospace`;
    ctx.textAlign = "left";
    ctx.textBaseline = "middle";
    const sign = finalDelta >= 0 ? "+" : "";
    ctx.fillText(
      `${sign}${finalDelta.toLocaleString("en-IN")}`,
      chartRight + css(4),
      zeroY,
    );
    ctx.restore();
  }
}

// ─── Main widget ──────────────────────────────────────────────────────────────

interface FootprintPanelParams {
  symbol?: string;
  exchange?: string;
}

interface FootprintInstrument {
  symbol: string;
  explicitExchange?: string;
}

function FootprintWidget(props: IDockviewPanelProps) {
  const panelParams = props.params as FootprintPanelParams | undefined;
  const panelSymbol = panelParams?.symbol;
  const panelExchange = panelParams?.exchange;
  const [instrument, setInstrument] = useState<FootprintInstrument>(() => ({
    symbol: panelSymbol ?? "NIFTY",
    explicitExchange: panelExchange,
  }));
  const [intervalLabel, setIntervalLabel] = useState("5m");

  useEffect(() => {
    setInstrument((current) => {
      const nextSymbol = panelSymbol ?? "NIFTY";
      if (
        current.symbol === nextSymbol
        && current.explicitExchange === panelExchange
      ) {
        return current;
      }
      return { symbol: nextSymbol, explicitExchange: panelExchange };
    });
  }, [panelExchange, panelSymbol]);

  const { symbol, explicitExchange } = instrument;
  const exchange = useMemo(
    () => resolveOrderFlowExchange(symbol, explicitExchange),
    [explicitExchange, symbol],
  );

  const handleSymbolChange = useCallback((nextSymbol: string) => {
    const nextExchange = resolveOrderFlowExchange(nextSymbol);
    setInstrument({ symbol: nextSymbol, explicitExchange: nextExchange });
    props.api.updateParameters({
      ...(panelParams ?? {}),
      symbol: nextSymbol,
      exchange: nextExchange,
    });
  }, [panelParams, props.api]);

  const intervalMinutes = useMemo(
    () => INTERVALS.find((iv) => iv.label === intervalLabel)?.minutes ?? 5,
    [intervalLabel],
  );

  const { data, isLoading, isError, error } = useOrderFlow(
    symbol,
    exchange,
    intervalMinutes * 60,
    20,
  );

  const isLive = data?.is_live ?? false;
  const displayIntervalLabel = formatIntervalLabel(data?.interval, intervalLabel);

  const columns = useMemo(() => {
    if (!data?.buckets) return [];
    return bucketsToColumns(data.buckets);
  }, [data]);

  const cumDelta = useMemo(() => cumulativeDelta(columns), [columns]);

  const canvasRef = useRef<HTMLCanvasElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const rafRef = useRef<number | null>(null);
  const sizeRef = useRef({ width: 0, height: 0 });

  // Use refs to avoid stale closures in rAF
  const columnsRef = useRef(columns);
  columnsRef.current = columns;
  const cumDeltaRef = useRef(cumDelta);
  cumDeltaRef.current = cumDelta;

  const paint = useCallback(() => {
    if (rafRef.current !== null) return;
    rafRef.current = requestAnimationFrame(() => {
      rafRef.current = null;
      const canvas = canvasRef.current;
      if (!canvas) return;
      const ctx = canvas.getContext("2d");
      if (!ctx) return;
      const dpr = window.devicePixelRatio || 1;
      drawFootprint(
        ctx,
        columnsRef.current,
        cumDeltaRef.current,
        canvas.width,
        canvas.height,
        dpr,
      );
    });
  }, []);

  // ResizeObserver — keep canvas resolution in sync with container DPR
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
      canvas.width = Math.floor(width * dpr);
      canvas.height = Math.floor(height * dpr);
      canvas.style.width = `${width}px`;
      canvas.style.height = `${height}px`;
      paint();
    });

    observer.observe(container);
    return () => observer.disconnect();
  }, [paint]);

  // Repaint when data changes
  useEffect(() => {
    paint();
  }, [columns, cumDelta, paint]);

  // Cleanup rAF on unmount
  useEffect(() => {
    return () => {
      if (rafRef.current !== null) cancelAnimationFrame(rafRef.current);
    };
  }, []);

  return (
    <div className="flex flex-col h-full bg-surface-base select-none">
      {/* Toolbar */}
      <div className="flex items-center gap-2 px-3 py-1.5 border-b border-border-default shrink-0">
        <BarChart className="size-3.5 text-indigo-400" aria-hidden="true" />
        <span className="text-xs font-medium text-text-secondary">Footprint</span>

        {/* Symbol */}
        <span className="sr-only" id="fp-symbol-label">Symbol</span>
        <Select value={symbol} onValueChange={handleSymbolChange}>
          <SelectTrigger
            className="h-6 w-28 text-xs border-border-default bg-surface-card text-text-primary focus:ring-0"
            aria-labelledby="fp-symbol-label"
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

        {/* Interval */}
        <span className="sr-only" id="fp-interval-label">Interval</span>
        <div className="flex items-center gap-0.5" role="group" aria-labelledby="fp-interval-label">
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

        <div className="ml-auto flex items-center gap-2">
          {isLoading && (
            <Badge
              variant="outline"
              className="text-xs border-blue-500/40 text-blue-400 bg-blue-500/10 h-5 px-1.5"
            >
              <Loader2 className="size-2.5 mr-1 animate-spin" aria-hidden="true" />
              Loading
            </Badge>
          )}
          {isError && (
            <Badge
              variant="outline"
              className="text-xs border-red-500/40 text-red-400 bg-red-500/10 h-5 px-1.5"
              aria-label={`Error: ${error instanceof Error ? error.message : "Unknown"}`}
            >
              <AlertCircle className="size-2.5 mr-1" aria-hidden="true" />
              Error
            </Badge>
          )}
          {!isLoading && !isError && columns.length > 0 && isLive && (
            <Badge
              variant="outline"
              className="text-xs border-emerald-500/40 text-emerald-400 bg-emerald-500/10 h-5 px-1.5"
              aria-label="Live footprint data"
            >
              <span
                className="size-1.5 rounded-full bg-emerald-400 mr-1 animate-pulse inline-block"
                aria-hidden="true"
              />
              Live
            </Badge>
          )}
          {!isLoading && !isError && columns.length > 0 && !isLive && (
            <Badge
              variant="outline"
              className="text-xs border-amber-500/40 text-amber-400 bg-amber-500/10 h-5 px-1.5"
              aria-label="Sample data — live aggregator not active"
            >
              <AlertCircle className="size-2.5 mr-1" aria-hidden="true" />
              Sample
            </Badge>
          )}
        </div>
      </div>

      {/* Legend */}
      <div className="flex items-center gap-3 px-3 py-1 border-b border-border-default shrink-0 text-xs text-text-muted">
        <div className="flex items-center gap-1">
          <div className="w-3 h-2 rounded-sm bg-profit" aria-hidden="true" />
          <span>Buy</span>
        </div>
        <div className="flex items-center gap-1">
          <div className="w-3 h-2 rounded-sm bg-loss" aria-hidden="true" />
          <span>Sell</span>
        </div>
        <div className="flex items-center gap-1">
          <div className="w-3 h-2 rounded-sm border border-amber-400" aria-hidden="true" />
          <span>POC</span>
        </div>
        <div className="flex items-center gap-1">
          <div className="w-3 border-t border-dashed border-indigo-400" aria-hidden="true" />
          <span>LTP</span>
        </div>
        <div className="flex items-center gap-1">
          <div className="w-3 border-t border-indigo-300" aria-hidden="true" />
          <span>Cum. Δ</span>
        </div>
        <span className="ml-auto tabular-nums">
          {columns.length} buckets &bull; {symbol} {displayIntervalLabel}
        </span>
      </div>

      {/* Canvas */}
      <div
        ref={containerRef}
        className="flex-1 relative min-h-0"
        role="img"
        aria-label={`Footprint chart for ${symbol} ${displayIntervalLabel}. Cells show buy (green) and sell (red) volume at each price level per time bucket. Delta value shown in each cell. Cumulative delta line at bottom.`}
      >
        <canvas
          ref={canvasRef}
          className="absolute inset-0 block"
          aria-hidden="true"
          data-testid="footprint-canvas"
        />

        {isLoading && columns.length === 0 && (
          <div className="absolute inset-0 flex flex-col items-center justify-center gap-3">
            <Skeleton className="h-3 w-48" />
            <Skeleton className="h-3 w-36" />
            <Skeleton className="h-3 w-40" />
            <span className="text-xs text-text-muted mt-1">Loading footprint data…</span>
          </div>
        )}
        {isError && (
          <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 text-loss/70">
            <AlertCircle className="size-8" aria-hidden="true" />
            <span className="text-sm">
              {error instanceof Error ? error.message : "Failed to load data"}
            </span>
            <span className="text-xs text-text-muted">Retrying automatically…</span>
          </div>
        )}
        {!isLoading && !isError && columns.length === 0 && (
          <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 text-text-muted">
            <BarChart className="size-8" aria-hidden="true" />
            <span className="text-sm">No footprint data</span>
          </div>
        )}
      </div>
    </div>
  );
}

export default memo(FootprintWidget);
