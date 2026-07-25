/**
 * ProfitTargetWidget — Risk/reward and position sizing calculator.
 *
 * Features:
 *   - Inputs: entry price, stop loss, target price, quantity, lot size
 *   - Calculates: risk-reward ratio, risk per trade, potential profit,
 *     required win rate for breakeven
 *   - Position sizing suggestion based on account capital and max risk %
 *   - Visual R:R bar (proportional green/red fill)
 *   - No external dependencies — pure maths + Tailwind
 */

import { useState, useMemo, useEffect, memo } from "react";
import { Target, AlertTriangle } from "lucide-react";
import { Input } from "@/components/ui/input";
import { useTrackBehavior } from "@/hooks/useTrackBehavior";
import {
  breakevenWinRate,
  formatRR,
  riskBudget,
  rrRatio as computeRR,
  sizeFixedFractional,
} from "@/lib/sizing";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface CalcResult {
  riskPerTrade: number;
  potentialProfit: number;
  rrRatio: number;
  breakEvenWinRate: number;    // percentage
  suggestedQty: number;
  /** True when the suggested single lot already breaches the risk budget. */
  suggestionExceedsRisk: boolean;
  /** Rupee risk of the suggested quantity — only meaningful when sized. */
  suggestedRisk: number;
  /** Rupee budget the suggestion was measured against. */
  riskBudgetAmount: number;
}

// ---------------------------------------------------------------------------
// Maths — sizing and risk/reward come from the shared kernel in lib/sizing.ts
// ---------------------------------------------------------------------------

function calculate(
  entry: number,
  stopLoss: number,
  target: number,
  qty: number,
  lotSize: number,
  capital: number,
  maxRiskPct: number,
): CalcResult | null {
  if (!entry || !stopLoss || !target || !qty || !lotSize) return null;
  const units = qty * lotSize;
  const risk = Math.abs(entry - stopLoss);
  const reward = Math.abs(target - entry);

  const rr = computeRR(entry, stopLoss, target);
  if (rr === null) return null;

  const riskPerTrade = risk * units;
  const potentialProfit = reward * units;

  const sized = sizeFixedFractional({
    capital,
    riskPct: maxRiskPct,
    stopDistance: risk,
    lotSize,
  });

  return {
    riskPerTrade,
    potentialProfit,
    rrRatio: rr,
    breakEvenWinRate: breakevenWinRate(rr),
    // Without usable capital/risk inputs there is no budget to size against,
    // so the operator's own quantity stands.
    suggestedQty: sized?.lots ?? qty,
    suggestionExceedsRisk: sized?.exceedsRisk ?? false,
    suggestedRisk: sized?.rupeeRisk ?? 0,
    riskBudgetAmount: riskBudget(capital, maxRiskPct),
  };
}

// ---------------------------------------------------------------------------
// R:R visual bar
// ---------------------------------------------------------------------------

function RRBar({ rrRatio }: { rrRatio: number }) {
  // Cap visual at 5:1 for display purposes
  const capped = Math.min(rrRatio, 5);
  const riskWidth = (1 / (1 + capped)) * 100;
  const rewardWidth = 100 - riskWidth;
  return (
    <div
      className="flex h-5 rounded overflow-hidden border border-border-default"
      aria-label={`Risk reward ratio ${rrRatio.toFixed(2)} to 1`}
    >
      <div
        className="bg-loss/60 flex items-center justify-center text-xxs text-white font-medium transition-all"
        style={{ width: `${riskWidth.toFixed(1)}%` }}
      >
        {riskWidth > 14 ? "Risk" : ""}
      </div>
      <div
        className="bg-profit/60 flex items-center justify-center text-xxs text-white font-medium transition-all"
        style={{ width: `${rewardWidth.toFixed(1)}%` }}
      >
        {rewardWidth > 14 ? `Reward (${rrRatio.toFixed(1)}R)` : ""}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Numeric input row
// ---------------------------------------------------------------------------

interface NumInputProps {
  id: string;
  label: string;
  value: string;
  onChange: (v: string) => void;
  step?: string;
  min?: string;
  placeholder?: string;
}

function NumInput({ id, label, value, onChange, step = "1", min = "0", placeholder = "0" }: NumInputProps) {
  return (
    <div className="flex items-center gap-2">
      <label htmlFor={id} className="text-xs text-text-muted w-28 shrink-0">
        {label}
      </label>
      <Input
        id={id}
        type="number"
        step={step}
        min={min}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        className="flex-1 h-7 text-xs font-mono text-right"
        aria-label={label}
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Result row
// ---------------------------------------------------------------------------

interface ResultRowProps {
  label: string;
  value: string;
  highlight?: "profit" | "loss" | "neutral";
}

function ResultRow({ label, value, highlight = "neutral" }: ResultRowProps) {
  const colour =
    highlight === "profit"
      ? "text-profit"
      : highlight === "loss"
      ? "text-loss"
      : "text-text-primary";
  return (
    <div className="flex items-center justify-between py-1 border-b border-border-default last:border-0">
      <span className="text-xs text-text-muted">{label}</span>
      <span className={`text-xs font-mono tabular-nums font-semibold ${colour}`}>{value}</span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Currency formatter
// ---------------------------------------------------------------------------

function fmtINR(v: number): string {
  return new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency: "INR",
    maximumFractionDigits: 0,
  }).format(v);
}

// ---------------------------------------------------------------------------
// Main widget
// ---------------------------------------------------------------------------

function ProfitTargetWidget() {
  const track = useTrackBehavior();

  const [entry, setEntry] = useState("22000");
  const [stopLoss, setStopLoss] = useState("21800");
  const [target, setTarget] = useState("22500");
  const [qty, setQty] = useState("1");
  const [lotSize, setLotSize] = useState("50");
  const [capital, setCapital] = useState("500000");
  const [maxRiskPct, setMaxRiskPct] = useState("1");

  const result = useMemo(
    () =>
      calculate(
        parseFloat(entry),
        parseFloat(stopLoss),
        parseFloat(target),
        parseFloat(qty),
        parseFloat(lotSize),
        parseFloat(capital),
        parseFloat(maxRiskPct),
      ),
    [entry, stopLoss, target, qty, lotSize, capital, maxRiskPct],
  );

  // Behaviour tracking is a side effect, so it belongs in an effect rather than
  // in the memo — inside useMemo it fired on every keystroke and ran twice
  // under StrictMode. Keyed on "has a result" so it reports once per session.
  const hasResult = result !== null;
  useEffect(() => {
    if (!hasResult) return;
    track("trade", "profit_target_calc");
  }, [hasResult, track]);

  return (
    <div className="h-full flex flex-col bg-surface-base overflow-hidden">

      {/* Header */}
      <div className="flex-none flex items-center gap-2 px-2 py-1.5 bg-surface-card border-b border-border-default">
        <Target size={13} className="text-accent shrink-0" aria-hidden="true" />
        <span className="text-xs font-semibold text-text-primary">Profit Target Calculator</span>
      </div>

      <div className="flex-1 min-h-0 overflow-y-auto p-2 space-y-3">

        {/* Trade inputs */}
        <fieldset className="space-y-2">
          <legend className="text-xxs text-text-muted uppercase tracking-wide mb-1.5">
            Trade Parameters
          </legend>
          <NumInput id="pt-entry" label="Entry Price" value={entry} onChange={setEntry} step="0.05" />
          <NumInput id="pt-sl" label="Stop Loss" value={stopLoss} onChange={setStopLoss} step="0.05" />
          <NumInput id="pt-target" label="Target Price" value={target} onChange={setTarget} step="0.05" />
          <NumInput id="pt-qty" label="Quantity (lots)" value={qty} onChange={setQty} min="1" />
          <NumInput id="pt-lotsize" label="Lot Size" value={lotSize} onChange={setLotSize} min="1" />
        </fieldset>

        {/* Position sizing inputs */}
        <fieldset className="space-y-2">
          <legend className="text-xxs text-text-muted uppercase tracking-wide mb-1.5">
            Position Sizing
          </legend>
          <NumInput id="pt-capital" label="Account Capital" value={capital} onChange={setCapital} />
          <NumInput id="pt-maxrisk" label="Max Risk %" value={maxRiskPct} onChange={setMaxRiskPct} step="0.1" min="0.1" />
        </fieldset>

        {/* Results */}
        {result ? (
          <div className="space-y-2">
            {/* R:R bar */}
            <div className="space-y-1">
              <div className="text-xxs text-text-muted uppercase tracking-wide">Risk / Reward Ratio</div>
              <RRBar rrRatio={result.rrRatio} />
            </div>

            {/* Result rows */}
            <div className="bg-surface-card border border-border-default rounded p-2">
              <ResultRow label="Risk per Trade" value={fmtINR(result.riskPerTrade)} highlight="loss" />
              <ResultRow label="Potential Profit" value={fmtINR(result.potentialProfit)} highlight="profit" />
              <ResultRow
                label="R:R Ratio"
                value={formatRR(result.rrRatio)}
                highlight={result.rrRatio >= 2 ? "profit" : result.rrRatio >= 1 ? "neutral" : "loss"}
              />
              <ResultRow
                label="Breakeven Win Rate"
                value={`${result.breakEvenWinRate.toFixed(1)}%`}
              />
              <ResultRow
                label="Suggested Qty (lots)"
                value={String(result.suggestedQty)}
                highlight={result.suggestionExceedsRisk ? "loss" : "neutral"}
              />
            </div>

            {/* Over-budget warning — one lot already breaches the stated risk */}
            {result.suggestionExceedsRisk && (
              <div
                role="status"
                className="flex items-start gap-1.5 text-xxs text-warning bg-warning/10 border border-warning/30 rounded px-2 py-1.5 leading-snug"
              >
                <AlertTriangle size={11} className="mt-px shrink-0" aria-hidden="true" />
                <span>
                  A single lot risks {fmtINR(result.suggestedRisk)} — more than the{" "}
                  {fmtINR(result.riskBudgetAmount)} you allowed. One lot is shown because it
                  is the smallest tradeable size; widen your capital, raise the max risk, or
                  tighten the stop to stay within budget.
                </span>
              </div>
            )}

            {/* Breakeven insight */}
            <div className="bg-surface-card border border-border-default rounded px-2 py-1.5 text-xs text-text-secondary">
              Win at least{" "}
              <span className="font-semibold text-text-primary">
                {result.breakEvenWinRate.toFixed(0)}%
              </span>{" "}
              of your trades to break even at this R:R.
            </div>
          </div>
        ) : (
          <div className="text-xs text-text-muted text-center py-4">
            Enter entry, stop loss and target to see results
          </div>
        )}
      </div>
    </div>
  );
}

export default memo(ProfitTargetWidget);
