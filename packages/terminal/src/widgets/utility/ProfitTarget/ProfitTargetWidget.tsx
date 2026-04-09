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

import { useState, useMemo, memo } from "react";
import { Target } from "lucide-react";
import { Input } from "@/components/ui/input";
import { useTrackBehavior } from "@/hooks/useTrackBehavior";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface CalcResult {
  riskPerTrade: number;
  potentialProfit: number;
  rrRatio: number;
  breakEvenWinRate: number;    // percentage
  suggestedQty: number;
}

// ---------------------------------------------------------------------------
// Maths
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
  if (risk === 0) return null;

  const riskPerTrade = risk * units;
  const potentialProfit = reward * units;
  const rrRatio = reward / risk;
  const breakEvenWinRate = (1 / (1 + rrRatio)) * 100;

  let suggestedQty = qty;
  if (capital > 0 && maxRiskPct > 0) {
    const maxRiskAmount = (capital * maxRiskPct) / 100;
    suggestedQty = Math.max(1, Math.floor(maxRiskAmount / (risk * lotSize)));
  }

  return { riskPerTrade, potentialProfit, rrRatio, breakEvenWinRate, suggestedQty };
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

  const result = useMemo(() => {
    const r = calculate(
      parseFloat(entry),
      parseFloat(stopLoss),
      parseFloat(target),
      parseFloat(qty),
      parseFloat(lotSize),
      parseFloat(capital),
      parseFloat(maxRiskPct),
    );
    if (r) track("trade", "profit_target_calc");
    return r;
  }, [entry, stopLoss, target, qty, lotSize, capital, maxRiskPct, track]);

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
                value={`${result.rrRatio.toFixed(2)} : 1`}
                highlight={result.rrRatio >= 2 ? "profit" : result.rrRatio >= 1 ? "neutral" : "loss"}
              />
              <ResultRow
                label="Breakeven Win Rate"
                value={`${result.breakEvenWinRate.toFixed(1)}%`}
              />
              <ResultRow
                label="Suggested Qty (lots)"
                value={String(result.suggestedQty)}
                highlight="neutral"
              />
            </div>

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
