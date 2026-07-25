/**
 * PositionSizingWidget — Advanced position sizing calculator.
 *
 * Features:
 *   - Inputs: account capital, risk per trade (%), stop loss distance, entry price
 *   - Methods: Fixed Fractional, Kelly Criterion, ATR-based
 *   - Calculates: position size (lots), rupee risk, max loss
 *   - Visual: core donut chart showing capital at risk vs available
 */

import { useState, useMemo, useEffect, memo } from "react";
import { Ruler, AlertTriangle } from "lucide-react";
import { FlintDonutBreakdown } from "@flinttrade/design-system";
import { Input } from "@/components/ui/input";
import { useTrackBehavior } from "@/hooks/useTrackBehavior";
import {
  kellyFraction,
  riskBudget,
  sizeFixedFractional,
  type FixedFractionalResult,
} from "@/lib/sizing";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type Method = "fixedFractional" | "kelly" | "atr";

/** A sizing result plus the budget it was measured against. */
interface SizingView {
  sized: FixedFractionalResult;
  /** Rupee budget the operator asked for — the yardstick for `exceedsRisk`. */
  budget: number;
}

// ---------------------------------------------------------------------------
// Calculations — all three methods reduce to the shared fixed-fractional
// kernel in lib/sizing.ts; only the risk percentage differs between them.
// ---------------------------------------------------------------------------

/** Size a position at a given risk percentage, pairing it with its budget. */
function size(
  capital: number,
  riskPct: number,
  slDistance: number,
  lotSize: number,
): SizingView | null {
  const sized = sizeFixedFractional({ capital, riskPct, stopDistance: slDistance, lotSize });
  if (!sized) return null;
  return { sized, budget: riskBudget(capital, riskPct) };
}

/** Kelly sizing: the stake percentage comes from the edge, not from the operator. */
function sizeKelly(
  capital: number,
  winRate: number,
  rewardRisk: number,
  slDistance: number,
  lotSize: number,
): SizingView | null {
  const stakePct = kellyFraction({ winRate, rewardRisk }) * 100;
  return size(capital, stakePct, slDistance, lotSize);
}

/** ATR sizing: the stop distance comes from volatility, the budget from risk %. */
function sizeATR(
  capital: number,
  riskPct: number,
  atr: number,
  atrMultiplier: number,
  lotSize: number,
): SizingView | null {
  return size(capital, riskPct, atr * atrMultiplier, lotSize);
}

// ---------------------------------------------------------------------------
// SVG Pie chart (2 segments)
// ---------------------------------------------------------------------------

interface PieChartProps {
  atRiskFraction: number;  // 0-1
}

function PieChart({ atRiskFraction }: PieChartProps) {
  const clampedFraction = Math.min(1, Math.max(0, atRiskFraction));
  const atRiskPct = (clampedFraction * 100).toFixed(1);
  const availablePct = ((1 - clampedFraction) * 100).toFixed(1);

  return (
    <FlintDonutBreakdown
      ariaLabel={`Capital allocation: ${atRiskPct}% at risk, ${availablePct}% available`}
      slices={[
        { label: "Available", value: 1 - clampedFraction, color: "#34d399" },
        { label: "At Risk", value: clampedFraction, color: "#f87171" },
      ]}
      className="size-20"
    />
  );
}

// ---------------------------------------------------------------------------
// Input row
// ---------------------------------------------------------------------------

interface NumInputProps {
  id: string;
  label: string;
  value: string;
  onChange: (v: string) => void;
  step?: string;
  min?: string;
}

function NumInput({ id, label, value, onChange, step = "1", min = "0" }: NumInputProps) {
  return (
    <div className="flex items-center gap-2">
      <label htmlFor={id} className="text-xs text-text-muted w-32 shrink-0">{label}</label>
      <Input
        id={id}
        type="number"
        step={step}
        min={min}
        value={value}
        onChange={(e) => onChange(e.target.value)}
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
  accent?: string;
}

function ResultRow({ label, value, accent }: ResultRowProps) {
  return (
    <div className="flex items-center justify-between py-1 border-b border-border-default last:border-0">
      <span className="text-xs text-text-muted">{label}</span>
      <span className={`text-xs font-mono tabular-nums font-semibold ${accent ?? "text-text-primary"}`}>
        {value}
      </span>
    </div>
  );
}

function fmtINR(v: number): string {
  return new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency: "INR",
    maximumFractionDigits: 0,
  }).format(v);
}

// ---------------------------------------------------------------------------
// Method tabs
// ---------------------------------------------------------------------------

const METHODS: { id: Method; label: string }[] = [
  { id: "fixedFractional", label: "Fixed %" },
  { id: "kelly", label: "Kelly" },
  { id: "atr", label: "ATR" },
];

// ---------------------------------------------------------------------------
// Main widget
// ---------------------------------------------------------------------------

function PositionSizingWidget() {
  const track = useTrackBehavior();
  const [method, setMethod] = useState<Method>("fixedFractional");

  // Shared fields
  const [capital, setCapital] = useState("500000");
  const [riskPct, setRiskPct] = useState("1");
  const [slDistance, setSlDistance] = useState("200");
  const [lotSize, setLotSize] = useState("50");

  // Kelly-specific
  const [winRate, setWinRate] = useState("55");
  const [rrRatio, setRRRatio] = useState("2");

  // ATR-specific
  const [atr, setAtr] = useState("180");
  const [atrMult, setAtrMult] = useState("1.5");

  const result = useMemo<SizingView | null>(() => {
    const cap = parseFloat(capital);
    const rp = parseFloat(riskPct);
    const sl = parseFloat(slDistance);
    const ls = parseFloat(lotSize);

    if (method === "fixedFractional") return size(cap, rp, sl, ls);
    if (method === "kelly") {
      return sizeKelly(cap, parseFloat(winRate), parseFloat(rrRatio), sl, ls);
    }
    return sizeATR(cap, rp, parseFloat(atr), parseFloat(atrMult), ls);
  }, [method, capital, riskPct, slDistance, lotSize, winRate, rrRatio, atr, atrMult]);

  // Behaviour tracking is a side effect, so it belongs in an effect rather than
  // in the memo — inside useMemo it fired on every keystroke and ran twice
  // under StrictMode. Keyed on "has a result" so it reports once per method.
  const hasResult = result !== null;
  useEffect(() => {
    if (!hasResult) return;
    track("trade", `position_sizing_calc_${method}`);
  }, [hasResult, method, track]);

  const handleMethodChange = (m: Method) => {
    setMethod(m);
    track("trade", `position_sizing_method_${m}`);
  };

  return (
    <div className="h-full flex flex-col bg-surface-base overflow-hidden" aria-label="Position Sizing widget">

      {/* Header */}
      <div className="flex-none flex items-center gap-2 px-2 py-1.5 bg-surface-card border-b border-border-default">
        <Ruler size={13} className="text-accent shrink-0" aria-hidden="true" />
        <span className="text-xs font-semibold text-text-primary">Position Sizing</span>
      </div>

      <div className="flex-1 min-h-0 overflow-y-auto p-2 space-y-3">

        {/* Method selector */}
        <div
          className="flex rounded border border-border-default overflow-hidden"
          role="tablist"
          aria-label="Position sizing method"
        >
          {METHODS.map((m) => (
            <button
              key={m.id}
              role="tab"
              aria-selected={method === m.id}
              onClick={() => handleMethodChange(m.id)}
              className={`flex-1 py-1 text-xs font-medium transition-colors ${
                method === m.id
                  ? "bg-accent text-white"
                  : "text-text-muted hover:text-text-primary hover:bg-surface-hover"
              }`}
            >
              {m.label}
            </button>
          ))}
        </div>

        {/* Shared inputs */}
        <fieldset className="space-y-2">
          <legend className="text-xxs text-text-muted uppercase tracking-wide mb-1.5">
            Account Parameters
          </legend>
          <NumInput id="ps-capital" label="Account Capital" value={capital} onChange={setCapital} />
          {method !== "kelly" && (
            <NumInput id="ps-risk" label="Risk per Trade %" value={riskPct} onChange={setRiskPct} step="0.1" min="0.1" />
          )}
          <NumInput id="ps-lotsize" label="Lot Size" value={lotSize} onChange={setLotSize} min="1" />
        </fieldset>

        {/* Method-specific inputs */}
        {method === "fixedFractional" && (
          <fieldset className="space-y-2">
            <legend className="text-xxs text-text-muted uppercase tracking-wide mb-1.5">
              Fixed Fractional
            </legend>
            <NumInput id="ps-sl" label="Stop Loss Distance" value={slDistance} onChange={setSlDistance} step="0.5" min="0.5" />
          </fieldset>
        )}

        {method === "kelly" && (
          <fieldset className="space-y-2">
            <legend className="text-xxs text-text-muted uppercase tracking-wide mb-1.5">
              Kelly Criterion (Half-Kelly)
            </legend>
            <NumInput id="ps-sl-kelly" label="Stop Loss Distance" value={slDistance} onChange={setSlDistance} step="0.5" min="0.5" />
            <NumInput id="ps-winrate" label="Win Rate %" value={winRate} onChange={setWinRate} step="1" min="1" />
            <NumInput id="ps-rr" label="Reward : Risk" value={rrRatio} onChange={setRRRatio} step="0.1" min="0.1" />
          </fieldset>
        )}

        {method === "atr" && (
          <fieldset className="space-y-2">
            <legend className="text-xxs text-text-muted uppercase tracking-wide mb-1.5">
              ATR-Based
            </legend>
            <NumInput id="ps-atr" label="ATR Value" value={atr} onChange={setAtr} step="0.5" min="0.5" />
            <NumInput id="ps-atrmult" label="ATR Multiplier" value={atrMult} onChange={setAtrMult} step="0.1" min="0.1" />
          </fieldset>
        )}

        {/* Results */}
        {result ? (
          <div className="space-y-3">
            {/* Over-budget warning — one lot already breaches the stated risk */}
            {result.sized.exceedsRisk && (
              <div
                role="status"
                className="flex items-start gap-1.5 text-xxs text-warning bg-warning/10 border border-warning/30 rounded px-2 py-1.5 leading-snug"
              >
                <AlertTriangle size={11} className="mt-px shrink-0" aria-hidden="true" />
                <span>
                  A single lot risks {fmtINR(result.sized.rupeeRisk)} — more than the{" "}
                  {fmtINR(result.budget)} you allowed. One lot is shown because it is the
                  smallest tradeable size; reduce the stop distance or the lot size to stay
                  within budget.
                </span>
              </div>
            )}

            {/* Pie chart */}
            <div className="flex items-center gap-4 bg-surface-card border border-border-default rounded p-3">
              <PieChart atRiskFraction={result.sized.capitalAtRiskPct / 100} />
              <div className="flex-1 space-y-1">
                <div className="flex items-center gap-1.5 text-xxs">
                  <span className="w-2.5 h-2.5 rounded-sm bg-loss/60 inline-block shrink-0" />
                  <span className="text-text-muted">At Risk</span>
                  <span className="ml-auto font-mono font-semibold text-loss">
                    {result.sized.capitalAtRiskPct.toFixed(2)}%
                  </span>
                </div>
                <div className="flex items-center gap-1.5 text-xxs">
                  <span className="w-2.5 h-2.5 rounded-sm bg-profit/50 inline-block shrink-0" />
                  <span className="text-text-muted">Available</span>
                  <span className="ml-auto font-mono font-semibold text-profit">
                    {(100 - result.sized.capitalAtRiskPct).toFixed(2)}%
                  </span>
                </div>
              </div>
            </div>

            {/* Result rows */}
            <div className="bg-surface-card border border-border-default rounded p-2">
              <ResultRow label="Position Size (lots)" value={String(result.sized.lots)} />
              <ResultRow label="Units (shares)" value={String(result.sized.units)} />
              <ResultRow
                label="Rupee Risk"
                value={fmtINR(result.sized.rupeeRisk)}
                accent={result.sized.exceedsRisk ? "text-warning" : "text-loss"}
              />
              <ResultRow
                label="Max Loss"
                value={fmtINR(result.sized.rupeeRisk)}
                accent={result.sized.exceedsRisk ? "text-warning" : "text-loss"}
              />
            </div>
          </div>
        ) : (
          <div className="text-xs text-text-muted text-center py-4">
            Fill in all fields to see position size
          </div>
        )}
      </div>
    </div>
  );
}

export default memo(PositionSizingWidget);
