/**
 * DOMHeatmapWidget — Historical Depth-of-Market heatmap for FlintTrade terminal.
 *
 * Visualises the Level-2 order book (DOM) accumulated over time as a canvas
 * heatmap.  Unlike the existing DepthHeatmapWidget (which uses synthetic data),
 * this widget polls the OpenAlgo REST depth endpoint every second and stores
 * snapshots in a rolling ring buffer, building up a real picture of where
 * large orders have been sitting and where they have been pulled.
 *
 * Canvas layout:
 *   Y-axis: price levels (ascending, lowest at bottom)
 *   X-axis: time (oldest on left, newest on right)
 *   Cell colour: bid side → blue/cyan ramp, ask side → red/orange ramp
 *   Colour intensity: log-scaled order size (brighter = more liquidity)
 *   Current price: dashed white horizontal line
 *   Colour-scale legend drawn in the right margin
 *
 * Performance:
 *   - Two-layer canvas: heatmap (expensive, repaints on data update) +
 *     crosshair overlay (cheap, repaints on mouse move at 60 fps).
 *   - rAF gating prevents redundant repaints.
 *   - ResizeObserver keeps both canvases DPR-aware.
 *   - Polling pauses when the browser tab is hidden.
 *
 * Accessibility:
 *   - Outer div has role="img" with descriptive aria-label.
 *   - Symbol selector has sr-only label.
 */

import {
  useRef,
  useEffect,
  useState,
  useCallback,
  memo,
  type MouseEvent as ReactMouseEvent,
} from "react";
import { Flame, AlertCircle } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { getDepth } from "@/services/api";
import type { MarketDepth } from "@/types/api";
import {
  normaliseDepth,
  type DepthLevel as SharedDepthLevel,
  type RawDepth,
} from "@/lib/depth";

// ─── Types ────────────────────────────────────────────────────────────────────

interface DOMCell {
  bidQty: number;
  askQty: number;
}

interface DOMSnapshot {
  /** Unix timestamp ms */
  ts: number;
  /** HH:MM:SS label */
  label: string;
  /** price → cell */
  levels: Map<number, DOMCell>;
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

const EXCHANGES: Record<string, string> = {
  NIFTY: "NSE_INDEX",
  BANKNIFTY: "NSE_INDEX",
  FINNIFTY: "NSE_INDEX",
  MIDCPNIFTY: "NSE_INDEX",
  RELIANCE: "NSE",
  TCS: "NSE",
};

/** Maximum number of snapshots kept in the ring buffer */
const MAX_SNAPSHOTS = 60;
/** Fallback price increment when the instrument's own tick is unknown. */
const DEFAULT_TICK_SIZE = 0.05;

/** Poll interval in ms — 1 s during market hours */
const POLL_INTERVAL_MS = 1_000;

// Canvas margins (CSS px)
const MARGIN_LEFT = 4;
const MARGIN_RIGHT = 64;
const MARGIN_TOP = 4;
const MARGIN_BOTTOM = 20;

// Canvas colours
const C_BG = "#0a0a0f";
const C_GRID = "#2a2a3a";
const C_TEXT = "#a1a1aa";
const C_TEXT_PRICE = "#e4e4e7";
const C_LTP = "#ffffff";

// ─── Colour ramps ─────────────────────────────────────────────────────────────

interface RGB {
  r: number;
  g: number;
  b: number;
}

const BID_RAMP: RGB[] = [
  { r: 10, g: 15, b: 40 },
  { r: 15, g: 50, b: 120 },
  { r: 30, g: 100, b: 200 },
  { r: 50, g: 180, b: 230 },
  { r: 180, g: 240, b: 255 },
  { r: 255, g: 255, b: 255 },
];

const ASK_RAMP: RGB[] = [
  { r: 40, g: 10, b: 10 },
  { r: 120, g: 30, b: 15 },
  { r: 200, g: 60, b: 30 },
  { r: 230, g: 130, b: 50 },
  { r: 255, g: 210, b: 150 },
  { r: 255, g: 255, b: 255 },
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

// ─── Snapshot builder ─────────────────────────────────────────────────────────

function buildSnapshot(depth: MarketDepth, tickSize = DEFAULT_TICK_SIZE): DOMSnapshot {
  const levels = new Map<number, DOMCell>();

  // Normalise through the shared depth module. This widget previously read
  // `row.price`/`row.quantity` straight off the payload, so any bridge that
  // emitted the short field names (p / qty / q, num_orders / o) produced an
  // empty heatmap with no error shown.
  const book = normaliseDepth(depth as unknown as RawDepth, Number.MAX_SAFE_INTEGER);

  const applyLevels = (rows: SharedDepthLevel[], side: "bid" | "ask") => {
    for (const row of rows) {
      if (!row.price || row.price <= 0) continue;
      // Round to the instrument's tick so levels aggregate. A hardcoded 0.05
      // was wrong for MCX and CDS contracts.
      const price = Math.round(row.price / tickSize) * tickSize;
      const existing = levels.get(price) ?? { bidQty: 0, askQty: 0 };
      if (side === "bid") {
        existing.bidQty += row.qty;
      } else {
        existing.askQty += row.qty;
      }
      levels.set(price, existing);
    }
  };

  applyLevels(book.bids, "bid");
  applyLevels(book.asks, "ask");

  const now = Date.now();
  const d = new Date(now);
  const pad = (n: number) => String(n).padStart(2, "0");
  const label = `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;

  return { ts: now, label, levels };
}

// ─── Drawing ──────────────────────────────────────────────────────────────────

function drawHeatmap(
  ctx: CanvasRenderingContext2D,
  snapshots: DOMSnapshot[],
  ltp: number,
  physW: number,
  physH: number,
  dpr: number,
): void {
  const css = (px: number) => px * dpr;

  ctx.fillStyle = C_BG;
  ctx.fillRect(0, 0, physW, physH);

  if (snapshots.length === 0) return;

  const chartLeft = css(MARGIN_LEFT);
  const chartRight = physW - css(MARGIN_RIGHT);
  const chartTop = css(MARGIN_TOP);
  const chartBottom = physH - css(MARGIN_BOTTOM);
  const chartW = chartRight - chartLeft;
  const chartH = chartBottom - chartTop;

  if (chartW <= 0 || chartH <= 0) return;

  // Collect all unique price levels across all snapshots
  const priceSet = new Set<number>();
  for (const snap of snapshots) {
    for (const price of snap.levels.keys()) priceSet.add(price);
  }
  const priceLevels = [...priceSet].sort((a, b) => a - b);
  const numLevels = priceLevels.length;
  if (numLevels === 0) return;

  const priceIdx = new Map(priceLevels.map((p, i) => [p, i]));
  const cellW = chartW / snapshots.length;
  const cellH = chartH / numLevels;

  // Find max qty for colour scaling (log scale for better contrast)
  let maxQty = 1;
  for (const snap of snapshots) {
    for (const cell of snap.levels.values()) {
      maxQty = Math.max(maxQty, cell.bidQty, cell.askQty);
    }
  }
  const logMax = Math.log1p(maxQty);

  // Draw cells
  for (let t = 0; t < snapshots.length; t++) {
    const snap = snapshots[t];
    const x = chartLeft + t * cellW;

    for (const [price, cell] of snap.levels.entries()) {
      const pi = priceIdx.get(price);
      if (pi === undefined) continue;
      const y = chartBottom - (pi + 1) * cellH;

      const totalQty = cell.bidQty + cell.askQty;
      if (totalQty === 0) continue;

      const dominantBid = cell.bidQty >= cell.askQty;
      const qty = dominantBid ? cell.bidQty : cell.askQty;
      // Log-scale intensity for better contrast on large spreads
      const intensity = Math.log1p(qty) / logMax;

      ctx.fillStyle = colorFromRamp(dominantBid ? BID_RAMP : ASK_RAMP, intensity);
      ctx.fillRect(x, y, Math.ceil(cellW) + 1, Math.ceil(cellH) + 1);
    }
  }

  // LTP line
  if (ltp > 0) {
    // Find closest price level
    let closestIdx = 0;
    let closestDist = Infinity;
    for (let i = 0; i < priceLevels.length; i++) {
      const d = Math.abs(priceLevels[i] - ltp);
      if (d < closestDist) {
        closestDist = d;
        closestIdx = i;
      }
    }
    const ltpY = chartBottom - (closestIdx + 0.5) * cellH;
    ctx.save();
    ctx.strokeStyle = C_LTP;
    ctx.lineWidth = dpr;
    ctx.globalAlpha = 0.7;
    ctx.setLineDash([css(4), css(3)]);
    ctx.beginPath();
    ctx.moveTo(chartLeft, ltpY);
    ctx.lineTo(chartRight, ltpY);
    ctx.stroke();
    ctx.restore();

    // LTP price label
    ctx.save();
    ctx.fillStyle = C_LTP;
    ctx.font = `bold ${css(9)}px "JetBrains Mono", monospace`;
    ctx.textAlign = "left";
    ctx.textBaseline = "middle";
    ctx.fillText(ltp.toLocaleString("en-IN"), chartRight + css(4), ltpY);
    ctx.restore();
  }

  // Price scale
  ctx.save();
  ctx.fillStyle = C_TEXT_PRICE;
  ctx.font = `${css(9)}px "JetBrains Mono", monospace`;
  ctx.textAlign = "left";
  ctx.textBaseline = "middle";
  const maxLabels = Math.floor(chartH / css(16));
  const labelStep = Math.max(1, Math.ceil(numLevels / maxLabels));
  for (let i = 0; i < numLevels; i += labelStep) {
    // Skip if already drawn as LTP label
    if (ltp > 0 && Math.abs(priceLevels[i] - ltp) < 0.1) continue;
    const y = chartBottom - (i + 0.5) * cellH;
    ctx.fillText(priceLevels[i].toLocaleString("en-IN"), chartRight + css(4), y);
  }
  ctx.restore();

  // Time labels
  ctx.save();
  ctx.fillStyle = C_TEXT;
  ctx.font = `${css(8)}px "JetBrains Mono", monospace`;
  ctx.textAlign = "center";
  ctx.textBaseline = "top";
  const maxTimeLabels = Math.floor(chartW / css(48));
  const timeStep = Math.max(1, Math.ceil(snapshots.length / maxTimeLabels));
  for (let t = 0; t < snapshots.length; t += timeStep) {
    const x = chartLeft + (t + 0.5) * cellW;
    const label = snapshots[t].label.slice(3); // "MM:SS"
    ctx.fillText(label, x, chartBottom + css(3));
  }
  ctx.restore();

  // Chart border
  ctx.save();
  ctx.strokeStyle = C_GRID;
  ctx.lineWidth = dpr;
  ctx.strokeRect(chartLeft, chartTop, chartW, chartH);
  ctx.restore();

  // Colour scale legend
  drawLegend(ctx, physW, dpr, maxQty);
}

function drawLegend(
  ctx: CanvasRenderingContext2D,
  physW: number,
  dpr: number,
  maxQty: number,
): void {
  const css = (px: number) => px * dpr;
  const legendW = css(10);
  const legendH = css(70);
  const legendX = physW - css(MARGIN_RIGHT) + css(46);
  const legendY = css(MARGIN_TOP + 4);
  const halfH = legendH / 2;

  // Bid gradient (bottom)
  for (let i = 0; i < Math.ceil(halfH); i++) {
    const intensity = i / halfH;
    ctx.fillStyle = colorFromRamp(BID_RAMP, intensity);
    ctx.fillRect(legendX, legendY + legendH - i, legendW, 2);
  }

  // Ask gradient (top)
  for (let i = 0; i < Math.ceil(halfH); i++) {
    const intensity = i / halfH;
    ctx.fillStyle = colorFromRamp(ASK_RAMP, intensity);
    ctx.fillRect(legendX, legendY + halfH - i, legendW, 2);
  }

  ctx.save();
  ctx.fillStyle = C_TEXT;
  ctx.font = `${css(7)}px "JetBrains Mono", monospace`;
  ctx.textAlign = "center";
  ctx.textBaseline = "top";
  ctx.fillText("Ask", legendX + legendW / 2, legendY - css(10));
  ctx.fillText("Bid", legendX + legendW / 2, legendY + legendH + css(2));
  ctx.textAlign = "left";
  ctx.fillText(String(maxQty), legendX + legendW + css(2), legendY);
  ctx.fillText("0", legendX + legendW + css(2), legendY + legendH - css(8));
  ctx.restore();
}

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
  ctx.strokeStyle = "rgba(255,255,255,0.3)";
  ctx.lineWidth = dpr;
  ctx.setLineDash([dpr * 3, dpr * 3]);
  ctx.beginPath();
  ctx.moveTo(0, y);
  ctx.lineTo(physW, y);
  ctx.stroke();
  ctx.beginPath();
  ctx.moveTo(x, 0);
  ctx.lineTo(x, physH);
  ctx.stroke();
  ctx.restore();
}

// ─── Main widget ──────────────────────────────────────────────────────────────

function DOMHeatmapWidget() {
  const [symbol, setSymbol] = useState("NIFTY");
  const [error, setError] = useState<string | null>(null);
  const [ltp, setLtp] = useState(0);

  const canvasRef = useRef<HTMLCanvasElement>(null);
  const crosshairRef = useRef<HTMLCanvasElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const rafRef = useRef<number | null>(null);
  const crosshairRafRef = useRef<number | null>(null);
  const sizeRef = useRef({ width: 0, height: 0 });
  const snapshotsRef = useRef<DOMSnapshot[]>([]);
  const ltpRef = useRef(0);
  ltpRef.current = ltp;

  const paint = useCallback(() => {
    if (rafRef.current !== null) return;
    rafRef.current = requestAnimationFrame(() => {
      rafRef.current = null;
      const canvas = canvasRef.current;
      if (!canvas) return;
      const ctx = canvas.getContext("2d");
      if (!ctx) return;
      const dpr = window.devicePixelRatio || 1;
      drawHeatmap(
        ctx,
        snapshotsRef.current,
        ltpRef.current,
        canvas.width,
        canvas.height,
        dpr,
      );
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
      const dpr = window.devicePixelRatio || 1;
      const physW = Math.floor(width * dpr);
      const physH = Math.floor(height * dpr);

      const canvas = canvasRef.current;
      if (canvas) {
        canvas.width = physW;
        canvas.height = physH;
        canvas.style.width = `${width}px`;
        canvas.style.height = `${height}px`;
      }
      const xCanvas = crosshairRef.current;
      if (xCanvas) {
        xCanvas.width = physW;
        xCanvas.height = physH;
        xCanvas.style.width = `${width}px`;
        xCanvas.style.height = `${height}px`;
      }
      paint();
    });

    observer.observe(container);
    return () => observer.disconnect();
  }, [paint]);

  // Polling loop — fetches depth every POLL_INTERVAL_MS, pauses when hidden
  useEffect(() => {
    // Reset on symbol change
    snapshotsRef.current = [];
    setError(null);
    setLtp(0);

    let intervalId: ReturnType<typeof setInterval> | null = null;
    const exchange = EXCHANGES[symbol] ?? "NSE";

    async function poll() {
      try {
        const depth = await getDepth(symbol, exchange);
        if (!depth) return;
        const snap = buildSnapshot(depth);
        snapshotsRef.current = [
          ...snapshotsRef.current.slice(-(MAX_SNAPSHOTS - 1)),
          snap,
        ];

        // Derive LTP from best bid/ask midpoint
        const bids = depth.buy;
        const asks = depth.sell;
        if (bids.length > 0 && asks.length > 0) {
          const bestBid = bids[0].price;
          const bestAsk = asks[0].price;
          const mid = (bestBid + bestAsk) / 2;
          setLtp(mid);
        }
        setError(null);
      } catch (e) {
        setError(e instanceof Error ? e.message : "Depth fetch error");
      }
      paint();
    }

    function startPolling() {
      if (intervalId !== null) return;
      void poll(); // immediate first fetch
      intervalId = setInterval(() => void poll(), POLL_INTERVAL_MS);
    }

    function stopPolling() {
      if (intervalId !== null) {
        clearInterval(intervalId);
        intervalId = null;
      }
    }

    function handleVisibility() {
      if (document.visibilityState === "visible") {
        startPolling();
      } else {
        stopPolling();
      }
    }

    if (document.visibilityState === "visible") startPolling();
    document.addEventListener("visibilitychange", handleVisibility);

    return () => {
      stopPolling();
      document.removeEventListener("visibilitychange", handleVisibility);
    };
  }, [symbol, paint]);

  // Cleanup rAF on unmount
  useEffect(() => {
    return () => {
      if (rafRef.current !== null) cancelAnimationFrame(rafRef.current);
      if (crosshairRafRef.current !== null) cancelAnimationFrame(crosshairRafRef.current);
    };
  }, []);

  // Mouse handlers
  const handleMouseMove = useCallback((e: ReactMouseEvent<HTMLDivElement>) => {
    if (crosshairRafRef.current !== null) return;
    const rect = (e.currentTarget as HTMLDivElement).getBoundingClientRect();
    const cssX = e.clientX - rect.left;
    const cssY = e.clientY - rect.top;
    crosshairRafRef.current = requestAnimationFrame(() => {
      crosshairRafRef.current = null;
      const xCanvas = crosshairRef.current;
      if (!xCanvas) return;
      const ctx = xCanvas.getContext("2d");
      if (!ctx) return;
      const dpr = window.devicePixelRatio || 1;
      drawCrosshair(ctx, cssX, cssY, xCanvas.width, xCanvas.height, dpr);
    });
  }, []);

  const handleMouseLeave = useCallback(() => {
    if (crosshairRafRef.current !== null) {
      cancelAnimationFrame(crosshairRafRef.current);
      crosshairRafRef.current = null;
    }
    const xCanvas = crosshairRef.current;
    if (!xCanvas) return;
    const ctx = xCanvas.getContext("2d");
    if (ctx) ctx.clearRect(0, 0, xCanvas.width, xCanvas.height);
  }, []);

  const snapshotCount = snapshotsRef.current.length;

  return (
    <div className="flex flex-col h-full bg-surface-base select-none">
      {/* Toolbar */}
      <div className="flex items-center gap-2 px-3 py-1.5 border-b border-border-default shrink-0">
        <Flame className="size-4 text-amber-400" aria-hidden="true" />
        <span className="text-xs font-medium text-text-secondary">DOM Heatmap</span>

        <span className="sr-only" id="domhm-symbol-label">Symbol</span>
        <Select value={symbol} onValueChange={setSymbol}>
          <SelectTrigger
            className="h-6 w-28 text-xs border-border-default bg-surface-card text-text-primary focus:ring-0"
            aria-labelledby="domhm-symbol-label"
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

        <div className="ml-auto flex items-center gap-2">
          {error && (
            <Badge
              variant="outline"
              className="text-xs border-red-500/40 text-red-400 bg-red-500/10 h-5 px-1.5"
              aria-label={`Error: ${error}`}
            >
              <AlertCircle className="size-2.5 mr-1" aria-hidden="true" />
              Error
            </Badge>
          )}
          {!error && snapshotCount > 0 && (
            <Badge
              variant="outline"
              className="text-xs border-emerald-500/40 text-emerald-400 bg-emerald-500/10 h-5 px-1.5"
              aria-label="Live depth data being accumulated"
            >
              <span
                className="size-1.5 rounded-full bg-emerald-400 mr-1 animate-pulse inline-block"
                aria-hidden="true"
              />
              Live
            </Badge>
          )}

          {ltp > 0 && (
            <div className="flex items-center gap-1">
              <span className="text-xs text-text-muted">Mid</span>
              <span className="font-mono text-xs font-semibold text-text-primary tabular-nums">
                {ltp.toLocaleString("en-IN", {
                  minimumFractionDigits: 2,
                  maximumFractionDigits: 2,
                })}
              </span>
            </div>
          )}

          <span className="text-xs text-text-muted tabular-nums">
            {snapshotCount}/{MAX_SNAPSHOTS} snaps
          </span>
        </div>
      </div>

      {/* Legend strip */}
      <div className="flex items-center gap-3 px-3 py-1 border-b border-border-default shrink-0 text-xs text-text-muted">
        <div className="flex items-center gap-1">
          <div className="w-3 h-2 rounded-sm bg-blue-500" aria-hidden="true" />
          <span>Bid (Buy)</span>
        </div>
        <div className="flex items-center gap-1">
          <div className="w-3 h-2 rounded-sm bg-red-500" aria-hidden="true" />
          <span>Ask (Sell)</span>
        </div>
        <div className="flex items-center gap-1">
          <div className="w-4 border-t border-dashed border-white/60" aria-hidden="true" />
          <span>Mid price</span>
        </div>
        <span className="ml-auto">Brighter = more liquidity</span>
      </div>

      {/* Canvas */}
      <div
        ref={containerRef}
        className="flex-1 relative min-h-0"
        role="img"
        aria-label={`DOM heatmap for ${symbol}. Shows bid volume (blue) and ask volume (red) at price levels over time. Brighter colours indicate larger order size. Mid price shown as dashed white line.`}
        data-testid="domheatmap-container"
        onMouseMove={handleMouseMove}
        onMouseLeave={handleMouseLeave}
      >
        <canvas
          ref={canvasRef}
          className="absolute inset-0 block pointer-events-none"
          aria-hidden="true"
          data-testid="domheatmap-canvas"
        />
        <canvas
          ref={crosshairRef}
          className="absolute inset-0 block pointer-events-none"
          aria-hidden="true"
          data-testid="domheatmap-crosshair"
          style={{ zIndex: 1 }}
        />

        {snapshotCount === 0 && !error && (
          <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 text-text-muted">
            <Flame className="size-8 text-amber-400/40" aria-hidden="true" />
            <span className="text-sm">Accumulating depth data…</span>
            <span className="text-xs">Level-2 snapshots will appear here</span>
          </div>
        )}
        {snapshotCount === 0 && error && (
          <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 text-loss/70">
            <AlertCircle className="size-8" aria-hidden="true" />
            <span className="text-sm">{error}</span>
            <span className="text-xs text-text-muted">
              Retrying every {POLL_INTERVAL_MS / 1000}s
            </span>
          </div>
        )}
      </div>
    </div>
  );
}

export default memo(DOMHeatmapWidget);
