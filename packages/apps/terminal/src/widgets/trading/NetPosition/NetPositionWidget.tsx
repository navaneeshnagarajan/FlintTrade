/**
 * NetPositionWidget — Aggregated net positions across all strategies.
 *
 * Features:
 *   - Symbol-level netting: long 2 lots + short 1 lot = net long 1 lot
 *   - Columns: symbol, net qty, avg price, LTP, net P&L, exposure
 *   - Group by underlying: NIFTY CE/PE legs collapsed under NIFTY header
 *   - Total row: aggregate exposure and P&L
 *   - Colour coding: long = profit green, short = loss red, flat = grey
 *   - Sample data when broker disconnected
 */

import { useState, useMemo, useEffect, memo } from "react";
import { Layers, ChevronDown, ChevronRight } from "lucide-react";
import { useTrackBehavior } from "@/hooks/useTrackBehavior";
import { useBrokerConnected } from "@/hooks/useBrokerConnected";
import { cn } from "@/lib/utils";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface RawPosition {
  strategy: string;
  symbol: string;       // full symbol e.g. "NIFTY 22400 CE 10APR"
  underlying: string;   // e.g. "NIFTY"
  qty: number;          // positive = long, negative = short
  avgPrice: number;
  ltp: number;
  lotSize: number;
}

export interface NetPositionRow {
  symbol: string;
  underlying: string;
  netQty: number;
  avgPrice: number;
  ltp: number;
  pnl: number;
  exposure: number;   // |netQty| * avgPrice * lotSize
}

// ---------------------------------------------------------------------------
// Sample data
// ---------------------------------------------------------------------------

export const SAMPLE_RAW_POSITIONS: RawPosition[] = [
  // Strategy A: Iron condor legs on NIFTY
  { strategy: "Iron Condor", symbol: "NIFTY 22200 CE 10APR", underlying: "NIFTY", qty:  2, avgPrice: 145, ltp: 120, lotSize: 50 },
  { strategy: "Iron Condor", symbol: "NIFTY 22600 CE 10APR", underlying: "NIFTY", qty: -2, avgPrice:  55, ltp:  38, lotSize: 50 },
  { strategy: "Iron Condor", symbol: "NIFTY 22000 PE 10APR", underlying: "NIFTY", qty: -2, avgPrice:  60, ltp:  42, lotSize: 50 },
  { strategy: "Iron Condor", symbol: "NIFTY 21800 PE 10APR", underlying: "NIFTY", qty:  2, avgPrice:  28, ltp:  19, lotSize: 50 },
  // Strategy B: long one NIFTY CE leg to hedge
  { strategy: "Scalper",     symbol: "NIFTY 22200 CE 10APR", underlying: "NIFTY", qty: -1, avgPrice: 145, ltp: 120, lotSize: 50 },
  // BANKNIFTY futures positions
  { strategy: "Scalper",     symbol: "BANKNIFTY FUT 24APR",  underlying: "BANKNIFTY", qty:  1, avgPrice: 48500, ltp: 48620, lotSize: 15 },
  { strategy: "Iron Condor", symbol: "BANKNIFTY FUT 24APR",  underlying: "BANKNIFTY", qty: -1, avgPrice: 48500, ltp: 48620, lotSize: 15 },
  // FINNIFTY calendar spread
  { strategy: "Theta",       symbol: "FINNIFTY 22000 CE 10APR", underlying: "FINNIFTY", qty: -1, avgPrice: 88, ltp: 72, lotSize: 40 },
  { strategy: "Theta",       symbol: "FINNIFTY 22000 CE 24APR", underlying: "FINNIFTY", qty:  1, avgPrice: 112, ltp: 125, lotSize: 40 },
];

// ---------------------------------------------------------------------------
// Netting logic
// ---------------------------------------------------------------------------

export function netPositions(raw: RawPosition[]): NetPositionRow[] {
  const map = new Map<string, {
    underlying: string;
    qtyWeightedPrice: number;
    totalQty: number;
    ltp: number;
    lotSize: number;
  }>();

  for (const pos of raw) {
    const existing = map.get(pos.symbol);
    if (!existing) {
      map.set(pos.symbol, {
        underlying: pos.underlying,
        qtyWeightedPrice: pos.qty * pos.avgPrice,
        totalQty: pos.qty,
        ltp: pos.ltp,
        lotSize: pos.lotSize,
      });
    } else {
      existing.qtyWeightedPrice += pos.qty * pos.avgPrice;
      existing.totalQty += pos.qty;
      existing.ltp = pos.ltp; // last seen
    }
  }

  const rows: NetPositionRow[] = [];
  for (const [symbol, agg] of map) {
    if (agg.totalQty === 0) continue; // flat — skip
    const avgPrice = agg.qtyWeightedPrice / agg.totalQty;
    const pnl = (agg.ltp - avgPrice) * agg.totalQty * agg.lotSize;
    const exposure = Math.abs(agg.totalQty) * avgPrice * agg.lotSize;
    rows.push({
      symbol,
      underlying: agg.underlying,
      netQty: agg.totalQty,
      avgPrice,
      ltp: agg.ltp,
      pnl,
      exposure,
    });
  }

  return rows.sort((a, b) => a.underlying.localeCompare(b.underlying) || a.symbol.localeCompare(b.symbol));
}

// ---------------------------------------------------------------------------
// Formatting helpers
// ---------------------------------------------------------------------------

function fmtPnl(v: number): string {
  const sign = v >= 0 ? "+" : "−";
  return `${sign}₹${Math.abs(v).toLocaleString("en-IN", { maximumFractionDigits: 0 })}`;
}

function fmtPrice(v: number): string {
  return v.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function fmtExposure(v: number): string {
  if (v >= 1_000_000) return `₹${(v / 100_000).toFixed(1)}L`;
  if (v >= 1_000) return `₹${(v / 1_000).toFixed(1)}K`;
  return `₹${v.toFixed(0)}`;
}

// ---------------------------------------------------------------------------
// Underlying group
// ---------------------------------------------------------------------------

interface UnderlyingGroupProps {
  underlying: string;
  rows: NetPositionRow[];
}

function UnderlyingGroup({ underlying, rows }: UnderlyingGroupProps) {
  const [expanded, setExpanded] = useState(true);

  const groupPnl = rows.reduce((s, r) => s + r.pnl, 0);
  const groupExposure = rows.reduce((s, r) => s + r.exposure, 0);

  return (
    <tbody>
      {/* Group header row */}
      <tr
        className="bg-surface-card cursor-pointer hover:bg-surface-hover transition-colors"
        onClick={() => setExpanded((o) => !o)}
        aria-expanded={expanded}
        aria-label={`${underlying} group — ${rows.length} positions`}
      >
        <td className="py-1.5 px-2 text-xs font-semibold text-text-primary" colSpan={2}>
          <span className="flex items-center gap-1">
            {expanded ? <ChevronDown size={11} /> : <ChevronRight size={11} />}
            {underlying}
            <span className="ml-1 text-xxs text-text-muted font-normal">({rows.length})</span>
          </span>
        </td>
        <td className="py-1.5 px-2 text-xs text-right text-text-muted" />
        <td className="py-1.5 px-2 text-xs text-right text-text-muted" />
        <td
          className={cn(
            "py-1.5 px-2 text-xs font-mono font-semibold text-right",
            groupPnl >= 0 ? "text-profit" : "text-loss",
          )}
        >
          {fmtPnl(groupPnl)}
        </td>
        <td className="py-1.5 px-2 text-xs text-right text-text-muted">
          {fmtExposure(groupExposure)}
        </td>
      </tr>

      {/* Position rows */}
      {expanded && rows.map((row) => (
        <tr
          key={row.symbol}
          className="border-t border-border-subtle hover:bg-surface-hover transition-colors"
          aria-label={`${row.symbol}: net qty ${row.netQty}`}
        >
          {/* Symbol */}
          <td className="py-1.5 pl-6 pr-2 text-xs text-text-secondary truncate max-w-32" title={row.symbol}>
            {row.symbol}
          </td>

          {/* Net qty */}
          <td
            className={cn(
              "py-1.5 px-2 text-xs font-mono tabular-nums font-semibold text-center",
              row.netQty > 0 ? "text-profit" : "text-loss",
            )}
          >
            {row.netQty > 0 ? `+${row.netQty}` : row.netQty}
          </td>

          {/* Avg price */}
          <td className="py-1.5 px-2 text-xs font-mono tabular-nums text-right text-text-secondary">
            {fmtPrice(row.avgPrice)}
          </td>

          {/* LTP */}
          <td className="py-1.5 px-2 text-xs font-mono tabular-nums text-right text-text-primary">
            {fmtPrice(row.ltp)}
          </td>

          {/* P&L */}
          <td
            className={cn(
              "py-1.5 px-2 text-xs font-mono tabular-nums font-semibold text-right",
              row.pnl >= 0 ? "text-profit" : "text-loss",
            )}
          >
            {fmtPnl(row.pnl)}
          </td>

          {/* Exposure */}
          <td className="py-1.5 px-2 text-xs font-mono tabular-nums text-right text-text-muted">
            {fmtExposure(row.exposure)}
          </td>
        </tr>
      ))}
    </tbody>
  );
}

// ---------------------------------------------------------------------------
// Main widget
// ---------------------------------------------------------------------------

function NetPositionWidget() {
  const track = useTrackBehavior();
  const isConnected = useBrokerConnected();

  useEffect(() => {
    track("trade", "widget_view_net_position");
  }, [track]);

  const netRows = useMemo(() => netPositions(SAMPLE_RAW_POSITIONS), []);

  const underlyings = useMemo(() => {
    const map = new Map<string, NetPositionRow[]>();
    for (const row of netRows) {
      const arr = map.get(row.underlying) ?? [];
      arr.push(row);
      map.set(row.underlying, arr);
    }
    return map;
  }, [netRows]);

  const totalPnl = netRows.reduce((s, r) => s + r.pnl, 0);
  const totalExposure = netRows.reduce((s, r) => s + r.exposure, 0);

  return (
    <div
      className="h-full flex flex-col bg-surface-base overflow-hidden"
      aria-label="Net Position widget"
    >
      {/* Header */}
      <div className="flex-none flex items-center gap-2 px-2 py-1.5 bg-surface-card border-b border-border-default flex-wrap">
        <Layers size={13} className="text-accent shrink-0" aria-hidden="true" />
        <span className="text-xs font-semibold text-text-primary">Net Positions</span>

        <span className="text-xxs text-text-muted">
          {netRows.length} position{netRows.length !== 1 ? "s" : ""}
        </span>

        <div className="flex-1" />

        <span
          className={cn(
            "text-sm font-bold font-mono tabular-nums",
            totalPnl >= 0 ? "text-profit" : "text-loss",
          )}
        >
          {fmtPnl(totalPnl)}
        </span>

        {!isConnected && (
          <span className="px-1.5 py-0.5 text-xxs bg-warning/10 text-warning border border-warning/30 rounded">
            Sample
          </span>
        )}
      </div>

      {/* Table */}
      <div className="flex-1 min-h-0 overflow-auto">
        <table className="w-full text-xs border-collapse" aria-label="Net positions table">
          <thead className="sticky top-0 z-10">
            <tr className="bg-surface-card border-b border-border-default">
              <th className="text-left py-1.5 px-2 text-xxs text-text-muted font-medium">Symbol</th>
              <th className="text-center py-1.5 px-2 text-xxs text-text-muted font-medium">Net Qty</th>
              <th className="text-right py-1.5 px-2 text-xxs text-text-muted font-medium">Avg</th>
              <th className="text-right py-1.5 px-2 text-xxs text-text-muted font-medium">LTP</th>
              <th className="text-right py-1.5 px-2 text-xxs text-text-muted font-medium">Net P&amp;L</th>
              <th className="text-right py-1.5 px-2 text-xxs text-text-muted font-medium">Exposure</th>
            </tr>
          </thead>

          {[...underlyings.entries()].map(([underlying, rows]) => (
            <UnderlyingGroup key={underlying} underlying={underlying} rows={rows} />
          ))}

          {/* Total row */}
          <tfoot>
            <tr className="bg-surface-card border-t-2 border-border-default">
              <td
                className="py-2 px-2 text-xs font-bold text-text-primary"
                colSpan={4}
              >
                Total
              </td>
              <td
                className={cn(
                  "py-2 px-2 text-xs font-mono tabular-nums font-bold text-right",
                  totalPnl >= 0 ? "text-profit" : "text-loss",
                )}
              >
                {fmtPnl(totalPnl)}
              </td>
              <td className="py-2 px-2 text-xs font-mono tabular-nums font-bold text-right text-text-secondary">
                {fmtExposure(totalExposure)}
              </td>
            </tr>
          </tfoot>
        </table>

        {netRows.length === 0 && (
          <div className="flex items-center justify-center h-24 text-text-muted text-sm">
            No open positions
          </div>
        )}
      </div>
    </div>
  );
}

export default memo(NetPositionWidget);
