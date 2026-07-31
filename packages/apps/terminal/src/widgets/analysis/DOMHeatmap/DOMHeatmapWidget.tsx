/**
 * DOMHeatmapWidget — the canonical depth-of-market heatmap for FlintTrade.
 *
 * Visualises the Level-2 order book (DOM) accumulated over time as a canvas
 * heatmap: where large orders have been sitting, and where they were pulled.
 *
 * This is the union of three widgets that drew the same picture:
 *
 *   - `domheatmap` (this one) contributed the live path: a 1 s poll of the
 *     REST depth endpoint into a 60-snapshot ring buffer.
 *   - `depthheatmap` (retired) contributed its deterministic seeded generator,
 *     kept whole in `depthHeatmapData.ts` and now wired as the EXPLORE-mode
 *     demo provider behind a permanent "Demo data" badge, plus its gamma 0.5
 *     power-scale intensity — offered here as a selectable alternative to the
 *     log1p scale rather than silently dropped. The two are different, valid
 *     readings of the same book: log1p keeps small resting orders legible,
 *     gamma pushes contrast toward the large ones.
 *   - `orderbookreplay` (retired) contributed the transport kernel —
 *     play/pause, single-step, the 1×/2×/4×/8× speed table and the accessible
 *     scrubber — which now drives the REAL snapshot ring instead of the
 *     `Math.random()` sample it used to replay.
 *
 * Canvas layout:
 *   Y-axis: price levels (ascending, lowest at bottom)
 *   X-axis: time (oldest on left, newest on right)
 *   Cell colour: bid side → blue/cyan ramp, ask side → red/orange ramp
 *   Colour intensity: order size, log1p- or gamma-scaled (selectable)
 *   Current price: dashed white horizontal line
 *   Replay playhead: solid amber vertical line
 *   Colour-scale legend drawn in the right margin
 *
 * View modes (workspace panel parameter `params.view`):
 *   - "live"   — accumulating heatmap, polls while the tab is visible.
 *   - "replay" — polling pauses so the ring is stable, and the transport bar
 *                scrubs it. This is how the retired `orderbookreplay` id
 *                resolves.
 *
 * Performance:
 *   - Two-layer canvas: heatmap (expensive, repaints on data update) +
 *     crosshair overlay (cheap, repaints on mouse move at 60 fps).
 *   - rAF gating prevents redundant repaints.
 *   - ResizeObserver keeps both canvases DPR-aware.
 *   - Hover hit-testing reuses the paint's own price-level ordering (cached by
 *     array identity), so the readout can never disagree with the pixels.
 *
 * Accessibility:
 *   - Outer div has role="img" with descriptive aria-label.
 *   - Symbol selector has an sr-only label.
 *   - Transport controls sit in a labelled toolbar; the scrubber is a
 *     role="slider" with arrow-key seeking.
 */

import {
  useRef,
  useEffect,
  useState,
  useCallback,
  memo,
  type MouseEvent as ReactMouseEvent,
} from "react";
import {
  Flame,
  AlertCircle,
  Play,
  Pause,
  RotateCcw,
  ChevronLeft,
  ChevronRight,
} from "lucide-react";
import type { WidgetProps } from "@/types/widgets";
import { Badge } from "@/components/ui/badge";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { cn } from "@/lib/utils";
import { getDepth } from "@/services/api";
import { useModeStore } from "@/stores/modeStore";
import { useTrackBehavior } from "@/hooks/useTrackBehavior";
import type { MarketDepth } from "@/types/api";
import {
  normaliseDepth,
  bookImbalance,
  type DepthLevel as SharedDepthLevel,
  type RawDepth,
} from "@/lib/depth";
import {
  generateDepthHeatmapData,
  shiftAndAppendColumn,
  type DepthHeatmapData,
} from "./depthHeatmapData";

// ─── Types ────────────────────────────────────────────────────────────────────

export interface DOMCell {
  bidQty: number;
  askQty: number;
}

export interface DOMSnapshot {
  /** Unix timestamp ms */
  ts: number;
  /** HH:MM:SS label */
  label: string;
  /** price → cell */
  levels: Map<number, DOMCell>;
}

/** The cell under the pointer, resolved back to real book values. */
export interface DOMHover {
  /** Column index into the snapshot array. */
  timeIndex: number;
  /** Row index into the sorted price levels (0 = lowest price). */
  priceIndex: number;
  price: number;
  bidQty: number;
  askQty: number;
  /** HH:MM:SS label of the hovered snapshot. */
  time: string;
}

/** Derived per-snapshot book statistics, shown while scrubbing. */
export interface DOMSnapshotStats {
  /** Best ask − best bid, or null when one side is empty. */
  spread: number | null;
  /** Signed imbalance −1 … +1 (positive = bid-heavy). */
  imbalance: number;
  cumBidQty: number;
  cumAskQty: number;
}

/** How cell intensity is derived from resting size. */
export type IntensityScale = "log" | "gamma";

/** Presentation of the heatmap. `replay` is the retired OrderBookReplay. */
export type ViewMode = "live" | "replay";

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

/** Price levels generated for the Explore-mode demo book. */
const DEMO_PRICE_LEVELS = 200;

/** Gamma exponent for the power scale (0.5 = square root). */
const GAMMA = 0.5;

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
const C_PLAYHEAD = "#fbbf24";

// ─── Transport ────────────────────────────────────────────────────────────────

type Speed = 1 | 2 | 4 | 8;
const SPEEDS: readonly Speed[] = [1, 2, 4, 8];
const TICK_MS: Record<Speed, number> = { 1: 800, 2: 400, 4: 200, 8: 100 };

// ─── Panel params ─────────────────────────────────────────────────────────────

interface DOMHeatmapPanelParams {
  symbol?: string;
  /** Initial view mode — how the retired `orderbookreplay` id selects replay. */
  view?: string;
  /** Initial intensity scale — how the retired `depthheatmap` id selects gamma. */
  scale?: string;
}

const VIEW_MODES: readonly ViewMode[] = ["live", "replay"];
const SCALES: readonly IntensityScale[] = ["log", "gamma"];

/** Resolves the workspace `params.view` panel parameter, defaulting to live. */
export function resolveViewMode(value: unknown): ViewMode {
  return typeof value === "string" && (VIEW_MODES as readonly string[]).includes(value)
    ? (value as ViewMode)
    : "live";
}

/** Resolves the workspace `params.scale` panel parameter, defaulting to log1p. */
export function resolveScale(value: unknown): IntensityScale {
  return typeof value === "string" && (SCALES as readonly string[]).includes(value)
    ? (value as IntensityScale)
    : "log";
}

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

/**
 * Map a resting size onto a 0…1 colour intensity.
 *
 * The two scales are genuinely different readings of the same book, which is
 * why both survived the merge as a setting:
 *   - `log`   — log1p compression. Small resting orders stay visible; the
 *               brightest cells are reserved for genuine outliers.
 *   - `gamma` — power scale with exponent 0.5 (square root). Contrast is
 *               pushed toward the large orders, so icebergs pop.
 *
 * @param qty - Resting quantity at the cell.
 * @param maxQty - Largest quantity anywhere in the visible window.
 * @param scale - Which reading to use.
 * @returns Intensity clamped to 0…1.
 */
export function computeIntensity(
  qty: number,
  maxQty: number,
  scale: IntensityScale,
): number {
  if (!(qty > 0) || !(maxQty > 0)) return 0;
  const raw =
    scale === "gamma"
      ? Math.pow(qty / maxQty, GAMMA)
      : Math.log1p(qty) / Math.log1p(maxQty);
  return Math.max(0, Math.min(1, raw));
}

// ─── Snapshot builders ────────────────────────────────────────────────────────

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

/**
 * Adapt the deterministic Explore-mode grid onto the live snapshot shape.
 *
 * Keeping one internal representation means Explore and Live share a single
 * drawing kernel, hit-test and transport — the demo path cannot drift into a
 * second renderer the way the retired `depthheatmap` widget did.
 *
 * @param data - A grid from `generateDepthHeatmapData`/`shiftAndAppendColumn`.
 * @param now - Timestamp for the newest column (injectable for tests).
 * @returns One snapshot per time column, oldest first.
 */
export function demoSnapshots(data: DepthHeatmapData, now = Date.now()): DOMSnapshot[] {
  const columns = data.timeLabels.length;
  const out: DOMSnapshot[] = [];
  for (let t = 0; t < columns; t++) {
    const levels = new Map<number, DOMCell>();
    for (let p = 0; p < data.priceLevels.length; p++) {
      const cell = data.grid[p]?.[t];
      if (!cell) continue;
      if (cell.bidVolume === 0 && cell.askVolume === 0) continue;
      levels.set(data.priceLevels[p], {
        bidQty: cell.bidVolume,
        askQty: cell.askVolume,
      });
    }
    out.push({
      ts: now - (columns - 1 - t) * POLL_INTERVAL_MS,
      label: data.timeLabels[t],
      levels,
    });
  }
  return out;
}

// ─── Geometry ─────────────────────────────────────────────────────────────────

/** Every distinct price level across the window, ascending. */
function collectPriceLevels(snapshots: DOMSnapshot[]): number[] {
  const priceSet = new Set<number>();
  for (const snap of snapshots) {
    for (const price of snap.levels.keys()) priceSet.add(price);
  }
  return [...priceSet].sort((a, b) => a - b);
}

/** Largest single-side quantity anywhere in the window (floor 1). */
function collectMaxQty(snapshots: DOMSnapshot[]): number {
  let maxQty = 1;
  for (const snap of snapshots) {
    for (const cell of snap.levels.values()) {
      maxQty = Math.max(maxQty, cell.bidQty, cell.askQty);
    }
  }
  return maxQty;
}

/**
 * Resolve a pointer position to the book values under it.
 *
 * Both heatmaps drew a crosshair but neither told the operator what it was
 * pointing at, so this is new to the merge. The price-level ordering is the
 * same one the painter uses, so the readout and the pixels cannot disagree.
 *
 * @param snapshots - The window being drawn.
 * @param cssX - Pointer X within the canvas container, in CSS px.
 * @param cssY - Pointer Y within the canvas container, in CSS px.
 * @param cssWidth - Container width in CSS px.
 * @param cssHeight - Container height in CSS px.
 * @param levels - Pre-collected price levels (defaults to collecting them).
 * @returns The hovered cell, or null when the pointer is outside the plot.
 */
export function hitTestCell(
  snapshots: DOMSnapshot[],
  cssX: number,
  cssY: number,
  cssWidth: number,
  cssHeight: number,
  levels?: number[],
): DOMHover | null {
  if (snapshots.length === 0) return null;

  const chartLeft = MARGIN_LEFT;
  const chartRight = cssWidth - MARGIN_RIGHT;
  const chartTop = MARGIN_TOP;
  const chartBottom = cssHeight - MARGIN_BOTTOM;
  const chartW = chartRight - chartLeft;
  const chartH = chartBottom - chartTop;
  if (chartW <= 0 || chartH <= 0) return null;
  if (cssX < chartLeft || cssX > chartRight) return null;
  if (cssY < chartTop || cssY > chartBottom) return null;

  const priceLevels = levels ?? collectPriceLevels(snapshots);
  if (priceLevels.length === 0) return null;

  const cellW = chartW / snapshots.length;
  const cellH = chartH / priceLevels.length;

  const timeIndex = Math.min(
    snapshots.length - 1,
    Math.max(0, Math.floor((cssX - chartLeft) / cellW)),
  );
  const priceIndex = Math.min(
    priceLevels.length - 1,
    Math.max(0, Math.floor((chartBottom - cssY) / cellH)),
  );

  const snap = snapshots[timeIndex];
  const price = priceLevels[priceIndex];
  const cell = snap.levels.get(price);

  return {
    timeIndex,
    priceIndex,
    price,
    bidQty: cell?.bidQty ?? 0,
    askQty: cell?.askQty ?? 0,
    time: snap.label,
  };
}

/**
 * Book statistics for a single snapshot, shown while scrubbing.
 *
 * Imbalance goes through the shared `bookImbalance` so this widget cannot show
 * a different number from the rest of the depth family.
 *
 * @param snap - The snapshot to summarise.
 * @returns Spread (null when a side is empty), signed imbalance, cumulative qty.
 */
export function snapshotStats(snap: DOMSnapshot): DOMSnapshotStats {
  const bids: SharedDepthLevel[] = [];
  const asks: SharedDepthLevel[] = [];
  let bestBid = -Infinity;
  let bestAsk = Infinity;

  for (const [price, cell] of snap.levels.entries()) {
    if (cell.bidQty > 0) {
      bids.push({ price, qty: cell.bidQty, orders: 0 });
      if (price > bestBid) bestBid = price;
    }
    if (cell.askQty > 0) {
      asks.push({ price, qty: cell.askQty, orders: 0 });
      if (price < bestAsk) bestAsk = price;
    }
  }

  const spread =
    Number.isFinite(bestBid) && Number.isFinite(bestAsk) ? bestAsk - bestBid : null;

  return {
    spread,
    imbalance: bookImbalance(bids, asks),
    cumBidQty: bids.reduce((sum, l) => sum + l.qty, 0),
    cumAskQty: asks.reduce((sum, l) => sum + l.qty, 0),
  };
}

// ─── Drawing ──────────────────────────────────────────────────────────────────

function drawHeatmap(
  ctx: CanvasRenderingContext2D,
  snapshots: DOMSnapshot[],
  ltp: number,
  physW: number,
  physH: number,
  dpr: number,
  scale: IntensityScale,
  playheadIndex: number | null,
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

  const priceLevels = collectPriceLevels(snapshots);
  const numLevels = priceLevels.length;
  if (numLevels === 0) return;

  const priceIdx = new Map(priceLevels.map((p, i) => [p, i]));
  const cellW = chartW / snapshots.length;
  const cellH = chartH / numLevels;

  const maxQty = collectMaxQty(snapshots);

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
      const intensity = computeIntensity(qty, maxQty, scale);

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

  // Replay playhead — the scrubbed column
  if (playheadIndex !== null && playheadIndex >= 0 && playheadIndex < snapshots.length) {
    const x = chartLeft + (playheadIndex + 0.5) * cellW;
    ctx.save();
    ctx.strokeStyle = C_PLAYHEAD;
    ctx.lineWidth = Math.max(dpr, css(1.5));
    ctx.beginPath();
    ctx.moveTo(x, chartTop);
    ctx.lineTo(x, chartBottom);
    ctx.stroke();
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

// ─── Scrubber (absorbed from OrderBookReplay) ────────────────────────────────

interface ScrubberProps {
  index: number;
  total: number;
  onSeek: (i: number) => void;
}

function Scrubber({ index, total, onSeek }: ScrubberProps) {
  const trackRef = useRef<HTMLDivElement>(null);
  const pct = total > 1 ? (index / (total - 1)) * 100 : 0;

  const seekFrom = useCallback(
    (clientX: number) => {
      const rect = trackRef.current?.getBoundingClientRect();
      if (!rect || total <= 1) return;
      const ratio = Math.max(0, Math.min(1, (clientX - rect.left) / rect.width));
      onSeek(Math.round(ratio * (total - 1)));
    },
    [total, onSeek],
  );

  return (
    <div
      ref={trackRef}
      role="slider"
      aria-valuemin={0}
      aria-valuemax={Math.max(0, total - 1)}
      aria-valuenow={index}
      aria-label="Replay position"
      tabIndex={0}
      className="relative flex-1 h-1.5 bg-border-default rounded-full cursor-pointer focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-accent"
      onPointerDown={(e) => { e.currentTarget.setPointerCapture(e.pointerId); seekFrom(e.clientX); }}
      onPointerMove={(e) => { if (e.buttons === 1) seekFrom(e.clientX); }}
      onKeyDown={(e) => {
        if (e.key === "ArrowLeft") { e.preventDefault(); onSeek(Math.max(0, index - 1)); }
        else if (e.key === "ArrowRight") { e.preventDefault(); onSeek(Math.min(total - 1, index + 1)); }
      }}
    >
      <div className="absolute inset-y-0 left-0 bg-accent rounded-full pointer-events-none" style={{ width: `${pct}%` }} />
      <div className="absolute top-1/2 -translate-y-1/2 -translate-x-1/2 w-3 h-3 rounded-full bg-accent shadow-sm pointer-events-none" style={{ left: `${pct}%` }} />
    </div>
  );
}

// ─── Main widget ──────────────────────────────────────────────────────────────

function DOMHeatmapWidget(props: WidgetProps) {
  const panelParams = props.params as DOMHeatmapPanelParams | undefined;

  const track = useTrackBehavior();
  const isExplore = useModeStore((s) => s.mode === "explore");

  const [symbol, setSymbol] = useState(() => panelParams?.symbol ?? "NIFTY");
  const [viewMode, setViewMode] = useState<ViewMode>(() => resolveViewMode(panelParams?.view));
  const [scale, setScale] = useState<IntensityScale>(() => resolveScale(panelParams?.scale));
  const [error, setError] = useState<string | null>(null);
  const [ltp, setLtp] = useState(0);
  const [snapshotCount, setSnapshotCount] = useState(0);
  const [hover, setHover] = useState<DOMHover | null>(null);

  // Transport state (absorbed from OrderBookReplay)
  const [index, setIndex] = useState(0);
  const [isPlaying, setIsPlaying] = useState(false);
  const [speed, setSpeed] = useState<Speed>(1);

  const canvasRef = useRef<HTMLCanvasElement>(null);
  const crosshairRef = useRef<HTMLCanvasElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const rafRef = useRef<number | null>(null);
  const crosshairRafRef = useRef<number | null>(null);
  const sizeRef = useRef({ width: 0, height: 0 });
  const snapshotsRef = useRef<DOMSnapshot[]>([]);
  const ltpRef = useRef(0);
  ltpRef.current = ltp;
  const scaleRef = useRef(scale);
  scaleRef.current = scale;
  const isReplay = viewMode === "replay";
  const indexRef = useRef(index);
  indexRef.current = index;
  const isReplayRef = useRef(isReplay);
  isReplayRef.current = isReplay;
  // Cache the sorted price levels by snapshot-array identity so hover
  // hit-testing does not re-scan every level on every pointer move.
  const levelCacheRef = useRef<{ src: DOMSnapshot[] | null; levels: number[] }>({
    src: null,
    levels: [],
  });

  useEffect(() => {
    track("trade", "widget_view_dom_heatmap");
  }, [track]);

  const priceLevelsFor = useCallback((snaps: DOMSnapshot[]): number[] => {
    if (levelCacheRef.current.src === snaps) return levelCacheRef.current.levels;
    const levels = collectPriceLevels(snaps);
    levelCacheRef.current = { src: snaps, levels };
    return levels;
  }, []);

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
        scaleRef.current,
        isReplayRef.current ? indexRef.current : null,
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

  // Reset the ring whenever the instrument or the data source changes.
  useEffect(() => {
    snapshotsRef.current = [];
    levelCacheRef.current = { src: null, levels: [] };
    setSnapshotCount(0);
    setError(null);
    setLtp(0);
    setIndex(0);
    setIsPlaying(false);
    setHover(null);
    paint();
  }, [symbol, isExplore, paint]);

  // ── Live source: REST poll into the ring ───────────────────────────────────
  // Replay pauses the poll so the ring the scrubber addresses is stable (and
  // so a widget nobody is watching live is not burning a request per second).
  useEffect(() => {
    if (isExplore || isReplay) return;

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
        setSnapshotCount(snapshotsRef.current.length);

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
  }, [symbol, isExplore, isReplay, paint]);

  // ── Explore source: the deterministic demo generator ───────────────────────
  // Same shape, same renderer, same transport — but always badged "Demo data".
  useEffect(() => {
    if (!isExplore) return;

    const seed = symbol.split("").reduce((acc, ch) => acc + ch.charCodeAt(0), 0);
    let data = generateDepthHeatmapData(DEMO_PRICE_LEVELS, MAX_SNAPSHOTS, seed);
    let tick = seed;

    const publish = () => {
      snapshotsRef.current = demoSnapshots(data);
      setSnapshotCount(snapshotsRef.current.length);
      setLtp(data.priceLevels[data.currentPriceIndex] ?? 0);
      paint();
    };

    publish();

    // Replay freezes the demo book too, so scrubbing addresses a stable ring.
    if (isReplay) return;

    let interval: ReturnType<typeof setInterval> | null = null;

    function start() {
      if (interval !== null) return;
      interval = setInterval(() => {
        tick += 1;
        data = shiftAndAppendColumn(data, tick);
        publish();
      }, POLL_INTERVAL_MS);
    }

    function stop() {
      if (interval !== null) {
        clearInterval(interval);
        interval = null;
      }
    }

    function handleVisibility() {
      if (document.visibilityState === "visible") start();
      else stop();
    }

    if (document.visibilityState === "visible") start();
    document.addEventListener("visibilitychange", handleVisibility);

    return () => {
      stop();
      document.removeEventListener("visibilitychange", handleVisibility);
    };
  }, [symbol, isExplore, isReplay, paint]);

  // Keep the scrubber inside the ring as it fills or resets.
  useEffect(() => {
    setIndex((i) => {
      if (snapshotCount === 0) return 0;
      return Math.min(i, snapshotCount - 1);
    });
  }, [snapshotCount]);

  // ── Transport timer (absorbed from OrderBookReplay) ────────────────────────
  useEffect(() => {
    if (!isReplay || !isPlaying || snapshotCount === 0) return;
    const timer = setInterval(() => {
      setIndex((i) => {
        if (i >= snapshotCount - 1) {
          setIsPlaying(false);
          return i;
        }
        return i + 1;
      });
    }, TICK_MS[speed]);
    return () => clearInterval(timer);
  }, [isReplay, isPlaying, speed, snapshotCount]);

  // ── Keyboard shortcuts — replay only ───────────────────────────────────────
  useEffect(() => {
    if (!isReplay) return;
    function onKey(e: KeyboardEvent) {
      // The scrubber calls preventDefault() on its own arrow keys. Without this
      // guard the event bubbles on to here and steps a SECOND time — a defect
      // carried in from OrderBookReplay, where one arrow press moved two
      // snapshots. Space on a focused button is likewise a native activation.
      if (e.defaultPrevented) return;
      const tag = (e.target as HTMLElement)?.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;
      if (e.key === " " && tag === "BUTTON") return;
      if (e.key === " " || e.key === "k") { e.preventDefault(); setIsPlaying((p) => !p); }
      else if (e.key === "ArrowLeft" && !e.shiftKey) { e.preventDefault(); setIndex((i) => Math.max(0, i - 1)); }
      else if (e.key === "ArrowRight" && !e.shiftKey) { e.preventDefault(); setIndex((i) => Math.min(Math.max(0, snapshotCount - 1), i + 1)); }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [isReplay, snapshotCount]);

  // Repaint when the presentation changes
  useEffect(() => {
    paint();
  }, [viewMode, scale, index, paint]);

  // Cleanup rAF on unmount
  useEffect(() => {
    return () => {
      if (rafRef.current !== null) cancelAnimationFrame(rafRef.current);
      if (crosshairRafRef.current !== null) cancelAnimationFrame(crosshairRafRef.current);
    };
  }, []);

  // ── Panel-param persistence ────────────────────────────────────────────────

  const handleSymbolChange = useCallback((next: string) => {
    setSymbol(next);
    props.api?.updateParameters({ symbol: next });
  }, [props.api]);

  const handleViewModeChange = useCallback((next: ViewMode) => {
    if (next === viewMode) return;
    setViewMode(next);
    if (next === "live") setIsPlaying(false);
    props.api?.updateParameters({ view: next });
  }, [props.api, viewMode]);

  const handleScaleChange = useCallback((next: IntensityScale) => {
    if (next === scale) return;
    setScale(next);
    props.api?.updateParameters({ scale: next });
  }, [props.api, scale]);

  // ── Pointer handlers: crosshair layer + value readout ──────────────────────

  const handleMouseMove = useCallback((e: ReactMouseEvent<HTMLDivElement>) => {
    const rect = (e.currentTarget as HTMLDivElement).getBoundingClientRect();
    const cssX = e.clientX - rect.left;
    const cssY = e.clientY - rect.top;

    // Value readout — only re-renders when the addressed cell actually changes.
    const snaps = snapshotsRef.current;
    const next = hitTestCell(
      snaps,
      cssX,
      cssY,
      rect.width,
      rect.height,
      priceLevelsFor(snaps),
    );
    setHover((prev) => {
      if (prev === null && next === null) return prev;
      if (
        prev !== null &&
        next !== null &&
        prev.timeIndex === next.timeIndex &&
        prev.priceIndex === next.priceIndex &&
        prev.bidQty === next.bidQty &&
        prev.askQty === next.askQty
      ) {
        return prev;
      }
      return next;
    });

    if (crosshairRafRef.current !== null) return;
    crosshairRafRef.current = requestAnimationFrame(() => {
      crosshairRafRef.current = null;
      const xCanvas = crosshairRef.current;
      if (!xCanvas) return;
      const ctx = xCanvas.getContext("2d");
      if (!ctx) return;
      const dpr = window.devicePixelRatio || 1;
      drawCrosshair(ctx, cssX, cssY, xCanvas.width, xCanvas.height, dpr);
    });
  }, [priceLevelsFor]);

  const handleMouseLeave = useCallback(() => {
    setHover(null);
    if (crosshairRafRef.current !== null) {
      cancelAnimationFrame(crosshairRafRef.current);
      crosshairRafRef.current = null;
    }
    const xCanvas = crosshairRef.current;
    if (!xCanvas) return;
    const ctx = xCanvas.getContext("2d");
    if (ctx) ctx.clearRect(0, 0, xCanvas.width, xCanvas.height);
  }, []);

  // ── Derived ────────────────────────────────────────────────────────────────

  const activeSnapshot =
    isReplay && snapshotCount > 0 ? snapshotsRef.current[index] : undefined;
  const stats = activeSnapshot ? snapshotStats(activeSnapshot) : null;

  const fmtQty = (v: number) => v.toLocaleString("en-IN");

  return (
    <div className="flex flex-col h-full bg-surface-base select-none">
      {/* Toolbar */}
      <div className="flex items-center gap-2 px-3 py-1.5 border-b border-border-default shrink-0">
        <Flame className="size-4 text-amber-400" aria-hidden="true" />
        <span className="text-xs font-medium text-text-secondary">DOM Heatmap</span>

        <span className="sr-only" id="domhm-symbol-label">Symbol</span>
        <Select value={symbol} onValueChange={handleSymbolChange}>
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

        {/* View mode — "replay" is the retired Order Book Replay widget */}
        <div className="flex items-center gap-0.5" role="group" aria-label="View mode">
          <button
            type="button"
            onClick={() => handleViewModeChange("live")}
            aria-pressed={viewMode === "live"}
            aria-label="Live accumulating view"
            className={cn(
              "px-2 py-0.5 text-xxs rounded transition-colors",
              viewMode === "live"
                ? "bg-accent/20 text-accent border border-accent/50"
                : "text-text-muted hover:text-text-primary hover:bg-surface-hover",
            )}
          >
            Live
          </button>
          <button
            type="button"
            onClick={() => handleViewModeChange("replay")}
            aria-pressed={viewMode === "replay"}
            aria-label="Replay the captured snapshots"
            className={cn(
              "px-2 py-0.5 text-xxs rounded transition-colors",
              viewMode === "replay"
                ? "bg-accent/20 text-accent border border-accent/50"
                : "text-text-muted hover:text-text-primary hover:bg-surface-hover",
            )}
          >
            Replay
          </button>
        </div>

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
          {/* Provenance. Explore-mode books come from the deterministic
              generator and are ALWAYS labelled — a heatmap of invented
              liquidity must never be mistakable for the real book. */}
          {isExplore && (
            <Badge
              variant="outline"
              className="text-xs border-amber-500/40 text-amber-400 bg-amber-500/10 h-5 px-1.5"
              role="status"
              aria-label="Showing generated demo depth — not a live order book"
              title="Explore mode: the book is generated from a deterministic seed, not a broker feed."
            >
              Demo data
            </Badge>
          )}
          {!isExplore && !error && snapshotCount > 0 && (
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

      {/* Legend strip + intensity scale */}
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

        <div className="ml-auto flex items-center gap-1">
          <span className="text-text-muted">Scale</span>
          <div className="flex items-center gap-0.5" role="group" aria-label="Intensity scale">
            <button
              type="button"
              onClick={() => handleScaleChange("log")}
              aria-pressed={scale === "log"}
              aria-label="Logarithmic intensity scale"
              title="log1p — keeps small resting orders legible"
              className={cn(
                "px-1.5 py-0.5 text-xxs font-mono rounded transition-colors",
                scale === "log"
                  ? "bg-accent/20 text-accent border border-accent/50"
                  : "text-text-muted hover:text-text-primary hover:bg-surface-hover",
              )}
            >
              Log
            </button>
            <button
              type="button"
              onClick={() => handleScaleChange("gamma")}
              aria-pressed={scale === "gamma"}
              aria-label="Gamma power intensity scale"
              title="Power scale (γ = 0.5) — pushes contrast toward large orders"
              className={cn(
                "px-1.5 py-0.5 text-xxs font-mono rounded transition-colors",
                scale === "gamma"
                  ? "bg-accent/20 text-accent border border-accent/50"
                  : "text-text-muted hover:text-text-primary hover:bg-surface-hover",
              )}
            >
              Gamma
            </button>
          </div>
        </div>
      </div>

      {/* Replay stats bar — the scrubbed snapshot's book */}
      {isReplay && stats && (
        <div
          className="flex-none flex items-center gap-4 px-3 py-1 border-b border-border-subtle text-xxs"
          data-testid="domheatmap-replay-stats"
        >
          <div className="flex items-center gap-1">
            <span className="text-text-muted">Spread</span>
            <span className="font-mono tabular-nums text-warning">
              {stats.spread === null ? "—" : stats.spread.toFixed(2)}
            </span>
          </div>
          <div className="flex items-center gap-1">
            <span className="text-text-muted">Imbalance</span>
            <span
              className={cn(
                "font-mono tabular-nums font-semibold",
                stats.imbalance > 0.1
                  ? "text-profit"
                  : stats.imbalance < -0.1
                    ? "text-loss"
                    : "text-text-secondary",
              )}
            >
              {stats.imbalance > 0 ? "+" : ""}{(stats.imbalance * 100).toFixed(1)}%
            </span>
          </div>
          <div className="flex items-center gap-1">
            <span className="text-profit font-mono tabular-nums">{fmtQty(stats.cumBidQty)}</span>
            <span className="text-text-muted">/</span>
            <span className="text-loss font-mono tabular-nums">{fmtQty(stats.cumAskQty)}</span>
          </div>
          <span className="ml-auto font-mono tabular-nums text-text-muted">
            {activeSnapshot?.label}
          </span>
        </div>
      )}

      {/* Canvas */}
      <div
        ref={containerRef}
        className="flex-1 relative min-h-0"
        role="img"
        aria-label={`DOM heatmap for ${symbol}${isExplore ? " (demo data)" : ""}. ${
          isReplay
            ? "Replay view: scrub the captured snapshots with the transport controls below."
            : "Live view: snapshots accumulate left to right."
        } Shows bid volume (blue) and ask volume (red) at price levels over time. Brighter colours indicate larger order size. Mid price shown as dashed white line.`}
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

        {/* Hover value readout — new to the merge; both widgets drew a
            crosshair but neither said what it pointed at. */}
        {hover && (
          <div
            className="absolute top-1 left-1 z-10 pointer-events-none rounded border border-border-default bg-surface-card/95 px-2 py-1 text-xxs shadow-sm"
            data-testid="domheatmap-readout"
          >
            <div className="font-mono tabular-nums text-text-primary font-semibold">
              {hover.price.toLocaleString("en-IN", {
                minimumFractionDigits: 2,
                maximumFractionDigits: 2,
              })}
            </div>
            <div className="flex items-center gap-2 font-mono tabular-nums">
              <span className="text-profit">Bid {fmtQty(hover.bidQty)}</span>
              <span className="text-loss">Ask {fmtQty(hover.askQty)}</span>
            </div>
            <div className="font-mono tabular-nums text-text-muted">{hover.time}</div>
          </div>
        )}

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

      {/* Transport bar — absorbed wholesale from OrderBookReplay, now driving
          the real snapshot ring instead of a Math.random() sample. */}
      {isReplay && (
        <div
          role="toolbar"
          aria-label="Replay controls"
          className="flex-none flex items-center gap-2 px-3 py-2 bg-surface-card border-t border-border-default"
        >
          <button
            type="button"
            onClick={() => setIsPlaying((p) => !p)}
            aria-label={isPlaying ? "Pause replay" : "Play replay"}
            title={`${isPlaying ? "Pause" : "Play"} (Space/k)`}
            disabled={snapshotCount === 0}
            className="flex items-center justify-center w-6 h-6 rounded text-text-secondary hover:text-text-primary hover:bg-surface-hover transition-colors disabled:opacity-40"
          >
            {isPlaying ? <Pause size={13} /> : <Play size={13} />}
          </button>

          <button
            type="button"
            onClick={() => { setIsPlaying(false); setIndex(0); }}
            aria-label="Reset to start"
            className="flex items-center justify-center w-6 h-6 rounded text-text-secondary hover:text-text-primary hover:bg-surface-hover transition-colors"
          >
            <RotateCcw size={12} />
          </button>

          <button
            type="button"
            onClick={() => setIndex((i) => Math.max(0, i - 1))}
            aria-label="Step back one snapshot"
            className="flex items-center justify-center w-6 h-6 rounded text-text-secondary hover:text-text-primary hover:bg-surface-hover transition-colors disabled:opacity-40"
            disabled={index === 0}
          >
            <ChevronLeft size={13} />
          </button>

          <button
            type="button"
            onClick={() => setIndex((i) => Math.min(Math.max(0, snapshotCount - 1), i + 1))}
            aria-label="Step forward one snapshot"
            className="flex items-center justify-center w-6 h-6 rounded text-text-secondary hover:text-text-primary hover:bg-surface-hover transition-colors disabled:opacity-40"
            disabled={snapshotCount === 0 || index >= snapshotCount - 1}
          >
            <ChevronRight size={13} />
          </button>

          <div className="w-px h-4 bg-border-default" aria-hidden="true" />

          <div className="flex items-center gap-0.5" role="group" aria-label="Replay speed">
            {SPEEDS.map((s) => (
              <button
                key={s}
                type="button"
                onClick={() => setSpeed(s)}
                aria-pressed={speed === s}
                aria-label={`${s}x speed`}
                className={cn(
                  "px-2 py-0.5 text-xxs font-mono rounded transition-colors",
                  speed === s
                    ? "bg-accent/20 text-accent border border-accent/50"
                    : "text-text-muted hover:text-text-primary hover:bg-surface-hover",
                )}
              >
                {s}x
              </button>
            ))}
          </div>

          <div className="w-px h-4 bg-border-default" aria-hidden="true" />

          <span className="text-xxs font-mono text-text-muted tabular-nums w-6 text-right shrink-0">
            {snapshotCount === 0 ? 0 : index + 1}
          </span>
          <Scrubber index={index} total={snapshotCount} onSeek={setIndex} />
          <span className="text-xxs font-mono text-text-muted tabular-nums w-6 shrink-0">
            {snapshotCount}
          </span>
        </div>
      )}
    </div>
  );
}

export default memo(DOMHeatmapWidget);
