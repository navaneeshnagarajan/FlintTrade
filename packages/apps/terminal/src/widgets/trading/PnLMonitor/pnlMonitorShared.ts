/**
 * Shared helpers for the P&L Monitor widget (dedup merge 2.10).
 *
 * The widget is the canonical union of three retired surfaces:
 *   - IntradayPnL  — the P&L maths (realised/unrealised split, tradebook
 *     partial-close booking, peak / max-drawdown tracking, per-strategy
 *     breakdown). Every semantic pin from its test suite survives in
 *     __tests__/PnLMonitorWidget.test.tsx.
 *   - MTM Monitor  — the Lightweight Charts curve, target/stop-loss price
 *     lines, staleness chip and error banner + retry.
 *   - P&L Dashboard tool — its Summary and Drawdown tabs (the Calendar tab
 *     moves to Trade Review in merge 2.12, not here).
 *
 * Every rupee figure derives through lib/pnl (positionMtm / realisedBySymbol /
 * realisedFromTrades) — never a raw broker `pnl` sum (CLAUDE.md quirk 4).
 */

import type { UTCTimestamp } from "lightweight-charts";
import { positionMtm } from "@/lib/pnl";
import { isMarketHours } from "@/lib/market";
import type { Position } from "@/types/api";

// ---------------------------------------------------------------------------
// View mode (workspace panel params)
// ---------------------------------------------------------------------------

/** Presentation of the P&L plane. `live` is both retired widgets' home view. */
export type PnLMonitorView = "live" | "summary" | "drawdown";

const VIEW_MODES: readonly PnLMonitorView[] = ["live", "summary", "drawdown"];

function isPnLMonitorView(value: unknown): value is PnLMonitorView {
  return typeof value === "string" && (VIEW_MODES as readonly string[]).includes(value);
}

/** Resolves the `params.view` panel parameter, defaulting to live. */
export function resolvePnLMonitorView(value: unknown): PnLMonitorView {
  return isPnLMonitorView(value) ? value : "live";
}

export interface PnLMonitorPanelParams {
  /** Initial view — how the retired `intradaypnl`/`mtmmonitor` ids reopen. */
  view?: string;
}

// ---------------------------------------------------------------------------
// Wire-format coercion
//
// Positionbook rows arrive unnormalised from real adapters: numerics as
// strings and some fields in snake_case. lib/pnl's positionMtm handles this
// for the P&L figure itself; the accessors below give the presentation layer
// the same tolerance (the retired P&L Dashboard Summary tab called
// `pos.averagePrice.toFixed(2)` on raw rows, which throws on a string-typed
// wire row — a crash the Intraday P&L suite's coercion pins were built to
// prevent).
// ---------------------------------------------------------------------------

type WirePosition = Position & {
  average_price?: string | number;
  avgPrice?: string | number;
  qty?: string | number;
  tradingsymbol?: string;
  strategy?: string;
};

/** Coerce a possibly string-typed broker numeric to a finite number, else null. */
export function toFiniteNumber(value: unknown): number | null {
  if (value === null || value === undefined || value === "") return null;
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
}

/** Coerced quantity — string "0" and missing values both mean flat. */
export function quantityOf(pos: Position): number {
  const wire = pos as WirePosition;
  return toFiniteNumber(wire.quantity ?? wire.qty) ?? 0;
}

/** Instrument symbol, matching the tradebook's `symbol` field for attribution. */
export function symbolOf(pos: Position): string {
  const wire = pos as WirePosition;
  return String(wire.symbol ?? wire.tradingsymbol ?? "");
}

/** Extract strategy tag from an OpenAlgo position — falls back to "default". */
export function strategyOf(pos: Position): string {
  return (pos as WirePosition).strategy ?? "default";
}

/** Coerced average price across every spelling adapters actually send. */
export function averagePriceOf(pos: Position): number | null {
  const wire = pos as WirePosition;
  return toFiniteNumber(wire.averagePrice ?? wire.average_price ?? wire.avgPrice);
}

/** Coerced last traded price. */
export function ltpOf(pos: Position): number | null {
  return toFiniteNumber(pos.ltp);
}

/** Coerced broker P&L percent — presentation only, may be null off the wire. */
export function pnlPercentOf(pos: Position): number | null {
  return toFiniteNumber(pos.pnlPercent);
}

// ---------------------------------------------------------------------------
// Formatting
// ---------------------------------------------------------------------------

const INR = new Intl.NumberFormat("en-IN", {
  maximumFractionDigits: 2,
  minimumFractionDigits: 2,
});

/** Exact rupee amount (2 dp) without sign, e.g. `₹1,200.00`. */
export function fmtINR(n: number): string {
  return `₹${INR.format(Math.abs(n))}`;
}

/** Signed exact rupee amount, e.g. `+₹400.00`. */
export function fmtSigned(n: number): string {
  const sign = n >= 0 ? "+" : "-";
  return `${sign}${fmtINR(n)}`;
}

const INR_WHOLE = new Intl.NumberFormat("en-IN", {
  style: "currency",
  currency: "INR",
  maximumFractionDigits: 0,
});

/** Whole-rupee currency format for chart axes and the target/SL readout. */
export function formatINRWhole(n: number): string {
  return INR_WHOLE.format(n);
}

/** Compact Indian notation for the Summary/Drawdown cards, e.g. `₹2.50L`. */
export function formatCompactINR(value: number): string {
  const abs = Math.abs(value);
  let formatted: string;
  if (abs >= 10_000_000) {
    formatted = `${(abs / 10_000_000).toFixed(2)}Cr`;
  } else if (abs >= 100_000) {
    formatted = `${(abs / 100_000).toFixed(2)}L`;
  } else if (abs >= 1_000) {
    formatted = `${(abs / 1_000).toFixed(2)}K`;
  } else {
    formatted = abs.toFixed(2);
  }
  return `${value < 0 ? "-" : ""}₹${formatted}`;
}

/** Tailwind text class for a P&L figure. */
export function pnlColor(n: number): string {
  if (n > 0) return "text-profit";
  if (n < 0) return "text-loss";
  return "text-text-muted";
}

/** IST HH:MM label for chart tick marks and peak/trough stamps. */
export function istTickFormatter(time: number): string {
  const utcMs = time * 1000;
  const istOffset = 5.5 * 60 * 60 * 1000;
  const d = new Date(utcMs + istOffset);
  const hh = d.getUTCHours().toString().padStart(2, "0");
  const mm = d.getUTCMinutes().toString().padStart(2, "0");
  return `${hh}:${mm}`;
}

// ---------------------------------------------------------------------------
// Staleness — a frozen P&L figure is worse than an error. Data older than the
// threshold (relative to the poll cadence) is flagged so the operator never
// trades against a silently stale number.
// ---------------------------------------------------------------------------

export function staleThresholdMs(): number {
  return isMarketHours() ? 30_000 : 150_000;
}

export function formatUpdatedAt(ms: number): string {
  return new Date(ms).toLocaleTimeString("en-IN", { timeZone: "Asia/Kolkata", hour12: false });
}

// ---------------------------------------------------------------------------
// Breakdown shapes
// ---------------------------------------------------------------------------

export interface StrategyPnL {
  strategy: string;
  pnl: number;
}

/** One point of the session equity curve. */
export interface MtmPoint {
  time: UTCTimestamp;
  value: number;
}

/** Build per-strategy P&L map from positions (lib/pnl per-row MTM). */
export function buildStrategyPnL(positions: Position[]): StrategyPnL[] {
  const map = new Map<string, number>();
  for (const pos of positions) {
    const s = strategyOf(pos);
    map.set(s, (map.get(s) ?? 0) + positionMtm(pos));
  }
  return Array.from(map.entries())
    .map(([strategy, pnl]) => ({ strategy, pnl }))
    .sort((a, b) => Math.abs(b.pnl) - Math.abs(a.pnl));
}
