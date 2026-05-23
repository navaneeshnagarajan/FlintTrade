/**
 * ImpliedMoveWidget — ATM straddle-based expected price range.
 *
 * Formula:
 *   Implied Move = ATM CE premium + ATM PE premium
 *   Upper bound  = Spot + Implied Move
 *   Lower bound  = Spot − Implied Move
 *
 * Probability zones are approximations derived from the log-normal model:
 *   1σ ≈ 68%  → ± 1× implied move
 *   2σ ≈ 95%  → ± 2× implied move
 *
 * Data source: sample data when disconnected; live when broker connected.
 */

import { useState, useMemo, useEffect, memo } from "react";
import { MoveHorizontal, RefreshCw } from "lucide-react";
import { cn } from "@/lib/utils";
import { useTrackBehavior } from "@/hooks/useTrackBehavior";
import { useBrokerConnected } from "@/hooks/useBrokerConnected";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface ImpliedMoveData {
  symbol: string;
  expiry: string;
  spot: number;
  atmStrike: number;
  cePremium: number;
  pePremium: number;
  impliedMove: number;
  upperBound: number;
  lowerBound: number;
  upper2Sigma: number;
  lower2Sigma: number;
  impliedMovePct: number;
}

// ---------------------------------------------------------------------------
// Sample data
// ---------------------------------------------------------------------------

export const SAMPLE_IMPLIED_MOVE: ImpliedMoveData = {
  symbol: "NIFTY",
  expiry: "24 Apr 2026",
  spot: 22350,
  atmStrike: 22350,
  cePremium: 142.5,
  pePremium: 138.2,
  impliedMove: 280.7,
  upperBound: 22630.7,
  lowerBound: 22069.3,
  upper2Sigma: 22911.4,
  lower2Sigma: 21788.6,
  impliedMovePct: 1.26,
};

export const SAMPLE_SYMBOLS: ImpliedMoveData[] = [
  SAMPLE_IMPLIED_MOVE,
  {
    symbol: "BANKNIFTY",
    expiry: "24 Apr 2026",
    spot: 48200,
    atmStrike: 48200,
    cePremium: 320.0,
    pePremium: 315.5,
    impliedMove: 635.5,
    upperBound: 48835.5,
    lowerBound: 47564.5,
    upper2Sigma: 49471.0,
    lower2Sigma: 46929.0,
    impliedMovePct: 1.32,
  },
];

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const INR = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 1 });

function fmt(n: number): string {
  return INR.format(n);
}

// ---------------------------------------------------------------------------
// Range bar
// ---------------------------------------------------------------------------

function RangeBar({ data }: { data: ImpliedMoveData }) {
  const { spot, lowerBound, upperBound, lower2Sigma, upper2Sigma } = data;

  // Compute positions as percentages within the 2σ range
  const totalRange = upper2Sigma - lower2Sigma;
  const pos = (v: number) =>
    Math.min(100, Math.max(0, ((v - lower2Sigma) / totalRange) * 100));

  const spotPct = pos(spot);
  const lb1Pct = pos(lowerBound);
  const ub1Pct = pos(upperBound);

  return (
    <div className="space-y-2" aria-label="Implied move range bar">
      {/* Range bar */}
      <div className="relative h-8 rounded bg-surface-hover overflow-visible mx-1">
        {/* 2σ zone (full width = bg) */}
        <div className="absolute inset-0 bg-accent/5 rounded" />

        {/* 1σ zone */}
        <div
          className="absolute inset-y-0 bg-accent/15 rounded"
          style={{ left: `${lb1Pct}%`, right: `${100 - ub1Pct}%` }}
        />

        {/* 1σ bound lines */}
        <div className="absolute inset-y-0 w-px bg-accent/50" style={{ left: `${lb1Pct}%` }} />
        <div className="absolute inset-y-0 w-px bg-accent/50" style={{ left: `${ub1Pct}%` }} />

        {/* Spot marker */}
        <div
          className="absolute top-1 bottom-1 w-0.5 bg-text-primary rounded-full shadow"
          style={{ left: `${spotPct}%`, transform: "translateX(-50%)" }}
        />

        {/* Spot label */}
        <div
          className="absolute -top-5 text-xxs font-mono text-text-primary whitespace-nowrap"
          style={{ left: `${spotPct}%`, transform: "translateX(-50%)" }}
        >
          {fmt(spot)}
        </div>
      </div>

      {/* Bound labels row */}
      <div className="flex justify-between text-xxs font-mono tabular-nums">
        <div className="text-left">
          <div className="text-loss font-semibold">{fmt(lower2Sigma)}</div>
          <div className="text-text-muted">−2σ (95%)</div>
        </div>
        <div className="text-center">
          <div className="text-text-secondary font-semibold">{fmt(lowerBound)}</div>
          <div className="text-text-muted">−1σ (68%)</div>
        </div>
        <div className="text-center">
          <div className="text-text-secondary font-semibold">{fmt(upperBound)}</div>
          <div className="text-text-muted">+1σ (68%)</div>
        </div>
        <div className="text-right">
          <div className="text-profit font-semibold">{fmt(upper2Sigma)}</div>
          <div className="text-text-muted">+2σ (95%)</div>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Premium breakdown row
// ---------------------------------------------------------------------------

function PremiumRow({ label, value, colour }: { label: string; value: number; colour: string }) {
  return (
    <div className="flex items-center justify-between">
      <span className="text-xs text-text-muted">{label}</span>
      <span className={cn("text-xs font-mono tabular-nums font-semibold", colour)}>
        ₹{fmt(value)}
      </span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main widget
// ---------------------------------------------------------------------------

const SYMBOLS = ["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX"];

function ImpliedMoveWidget() {
  const track = useTrackBehavior();
  const isConnected = useBrokerConnected();

  const [symbolIdx, setSymbolIdx] = useState(0);
  const [refreshKey, setRefreshKey] = useState(0);

  useEffect(() => {
    track("trade", "widget_view_implied_move");
  }, [track]);

  // In live mode we would call an API; use sample data for now
  const data: ImpliedMoveData = useMemo(
    () => SAMPLE_SYMBOLS[symbolIdx % SAMPLE_SYMBOLS.length] ?? SAMPLE_IMPLIED_MOVE,
    // refreshKey included so manual refresh triggers re-render
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [symbolIdx, refreshKey],
  );

  const selectedSymbol = SYMBOLS[symbolIdx] ?? "NIFTY";

  return (
    <div
      className="h-full flex flex-col bg-surface-base overflow-hidden"
      aria-label="Implied Move widget"
    >
      {/* Header */}
      <div className="flex-none flex items-center gap-2 px-2 py-1.5 bg-surface-card border-b border-border-default">
        <MoveHorizontal size={13} className="text-text-muted shrink-0" aria-hidden="true" />
        <span className="text-xs font-semibold text-text-primary">Implied Move</span>
        {!isConnected && (
          <span className="px-1.5 py-0.5 text-xxs bg-warning/10 text-warning border border-warning/30 rounded">
            Sample
          </span>
        )}
        <div className="flex-1" />
        {/* Symbol picker */}
        <Select value={selectedSymbol} onValueChange={(v) => setSymbolIdx(SYMBOLS.indexOf(v))}>
          <SelectTrigger className="h-6 px-2 text-xs w-32" aria-label="Select symbol">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {SYMBOLS.map((s) => (
              <SelectItem key={s} value={s} className="text-xs">{s}</SelectItem>
            ))}
          </SelectContent>
        </Select>
        <button
          onClick={() => setRefreshKey((k) => k + 1)}
          className="p-1 rounded text-text-muted hover:text-text-primary hover:bg-surface-hover transition-colors"
          title="Refresh"
          aria-label="Refresh implied move"
        >
          <RefreshCw size={11} />
        </button>
      </div>

      {/* Body */}
      <div className="flex-1 min-h-0 overflow-y-auto px-3 py-3 space-y-4">

        {/* Key stat */}
        <div className="flex items-center justify-between bg-surface-card rounded-lg px-3 py-2.5 border border-border-default">
          <div>
            <div className="text-xxs text-text-muted uppercase tracking-wide mb-0.5">
              Implied Move ({data.expiry})
            </div>
            <div className="text-lg font-bold font-mono tabular-nums text-text-primary">
              ±₹{fmt(data.impliedMove)}
            </div>
            <div className="text-xs text-text-muted font-mono">
              ±{data.impliedMovePct.toFixed(2)}% of spot
            </div>
          </div>
          <div className="text-right">
            <div className="text-xxs text-text-muted uppercase tracking-wide mb-0.5">ATM Strike</div>
            <div className="text-base font-bold font-mono tabular-nums text-text-secondary">
              {fmt(data.atmStrike)}
            </div>
            <div className="text-xxs text-text-muted">Spot {fmt(data.spot)}</div>
          </div>
        </div>

        {/* Range visualisation */}
        <section aria-labelledby="im-range">
          <p id="im-range" className="text-xxs font-medium text-text-muted uppercase tracking-wide mb-3">
            Expected Range
          </p>
          <RangeBar data={data} />
        </section>

        {/* Premium breakdown */}
        <section aria-labelledby="im-premium" className="bg-surface-card rounded-lg border border-border-default px-3 py-2.5 space-y-1.5">
          <p id="im-premium" className="text-xxs font-medium text-text-muted uppercase tracking-wide mb-2">
            ATM Straddle Premiums
          </p>
          <PremiumRow label="ATM CE Premium" value={data.cePremium} colour="text-profit" />
          <PremiumRow label="ATM PE Premium" value={data.pePremium} colour="text-loss" />
          <div className="border-t border-border-subtle pt-1.5">
            <PremiumRow label="Total (Implied Move)" value={data.impliedMove} colour="text-accent" />
          </div>
        </section>

        {/* Probability zones table */}
        <section aria-labelledby="im-zones">
          <p id="im-zones" className="text-xxs font-medium text-text-muted uppercase tracking-wide mb-1.5">
            Probability Zones
          </p>
          <table className="w-full text-xs" aria-label="Probability zones table">
            <thead>
              <tr className="border-b border-border-subtle">
                <th className="text-left py-1 text-xxs text-text-muted font-medium">Zone</th>
                <th className="text-center py-1 text-xxs text-text-muted font-medium">Lower</th>
                <th className="text-center py-1 text-xxs text-text-muted font-medium">Upper</th>
                <th className="text-right py-1 text-xxs text-text-muted font-medium">Prob.</th>
              </tr>
            </thead>
            <tbody>
              <tr className="border-b border-border-subtle">
                <td className="py-1 text-text-secondary">1σ</td>
                <td className="py-1 text-center font-mono tabular-nums text-loss">{fmt(data.lowerBound)}</td>
                <td className="py-1 text-center font-mono tabular-nums text-profit">{fmt(data.upperBound)}</td>
                <td className="py-1 text-right font-mono text-text-primary">68%</td>
              </tr>
              <tr>
                <td className="py-1 text-text-secondary">2σ</td>
                <td className="py-1 text-center font-mono tabular-nums text-loss">{fmt(data.lower2Sigma)}</td>
                <td className="py-1 text-center font-mono tabular-nums text-profit">{fmt(data.upper2Sigma)}</td>
                <td className="py-1 text-right font-mono text-text-primary">95%</td>
              </tr>
            </tbody>
          </table>
        </section>

      </div>
    </div>
  );
}

export default memo(ImpliedMoveWidget);
