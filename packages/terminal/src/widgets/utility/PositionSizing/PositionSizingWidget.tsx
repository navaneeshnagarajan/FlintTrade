/**
 * PositionSizingWidget — Advanced position sizing calculator.
 *
 * Features:
 *   - Inputs: account capital, risk per trade (%), stop loss distance, entry price
 *   - Methods: Fixed Fractional, Kelly Criterion, ATR-based
 *   - Calculates: position size (lots), rupee risk, max loss
 *   - Visual: pie chart (SVG) showing capital at risk vs available
 *   - No external dependencies — pure maths + Tailwind
 */

import { useState, useMemo, memo } from "react";
import { Ruler } from "lucide-react";
import { Input } from "@/components/ui/input";
import { useTrackBehavior } from "@/hooks/useTrackBehavior";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type Method = "fixedFractional" | "kelly" | "atr";

interface SizingResult {
  lots: number;
  units: number;
  rupeeRisk: number;
  maxLoss: number;
  capitalAtRisk: number;  // fraction 0-1
}

// ---------------------------------------------------------------------------
// Calculations
// ---------------------------------------------------------------------------

function calcFixedFractional(
  capital: number,
  riskPct: number,
  slDistance: number,
  lotSize: number,
): SizingResult | null {
  if (!capital || !riskPct || !slDistance || !lotSize) return null;
  const maxRisk = (capital * riskPct) / 100;
  const riskPerLot = slDistance * lotSize;
  if (riskPerLot <= 0) return null;
  const lots = Math.max(1, Math.floor(maxRisk / riskPerLot));
  const units = lots * lotSize;
  const rupeeRisk = riskPerLot * lots;
  return {
    lots,
    units,
    rupeeRisk,
    maxLoss: rupeeRisk,
    capitalAtRisk: rupeeRisk / capital,
  };
}

function calcKelly(
  capital: number,
  winRate: number,   // 0-100
  rrRatio: number,   // reward:risk
  slDistance: number,
  lotSize: number,
): SizingResult | null {
  if (!capital || !winRate || !rrRatio || !slDistance || !lotSize) return null;
  const p = winRate / 100;
  const q = 1 - p;
  // Kelly fraction: (p * rrRatio - q) / rrRatio
  const kellyFraction = Math.max(0, (p * rrRatio - q) / rrRatio);
  // Use half-Kelly for safety
  const halfKelly = kellyFraction / 2;
  const maxRisk = capital * halfKelly;
  const riskPerLot = slDistance * lotSize;
  if (riskPerLot <= 0) return null;
  const lots = Math.max(1, Math.floor(maxRisk / riskPerLot));
  const units = lots * lotSize;
  const rupeeRisk = riskPerLot * lots;
  return {
    lots,
    units,
    rupeeRisk,
    maxLoss: rupeeRisk,
    capitalAtRisk: rupeeRisk / capital,
  };
}

function calcATR(
  capital: number,
  riskPct: number,
  atr: number,
  atrMultiplier: number,
  lotSize: number,
): SizingResult | null {
  if (!capital || !riskPct || !atr || !atrMultiplier || !lotSize) return null;
  const slDistance = atr * atrMultiplier;
  return calcFixedFractional(capital, riskPct, slDistance, lotSize);
}

// ---------------------------------------------------------------------------
// SVG Pie chart (2 segments)
// ---------------------------------------------------------------------------

interface PieChartProps {
  atRiskFraction: number;  // 0-1
  size?: number;
}

function PieChart({ atRiskFraction, size = 80 }: PieChartProps) {
  const r = size / 2 - 4;
  const cx = size / 2;
  const cy = size / 2;
  const clampedFraction = Math.min(1, Math.max(0, atRiskFraction));
  const angle = clampedFraction * 2 * Math.PI;

  // Full circle edge case
  if (clampedFraction >= 0.999) {
    return (
      <svg width={size} height={size} aria-label={`Capital allocation: ${(clampedFraction * 100).toFixed(1)}% at risk`}>
        <circle cx={cx} cy={cy} r={r} fill="currentColor" className="text-loss/60" />
      </svg>
    );
  }
  if (clampedFraction <= 0.001) {
    return (
      <svg width={size} height={size} aria-label="Capital allocation: 0% at risk">
        <circle cx={cx} cy={cy} r={r} fill="currentColor" className="text-profit/60" />
      </svg>
    );
  }

  const x1 = cx + r * Math.sin(angle);
  const y1 = cy - r * Math.cos(angle);
  const largeArc = clampedFraction > 0.5 ? 1 : 0;

  const riskPath = `M ${cx},${cy} L ${cx},${cy - r} A ${r},${r} 0 ${largeArc},1 ${x1.toFixed(2)},${y1.toFixed(2)} Z`;
  const safePath = `M ${cx},${cy} L ${x1.toFixed(2)},${y1.toFixed(2)} A ${r},${r} 0 ${1 - largeArc},1 ${cx},${cy - r} Z`;

  return (
    <svg
      width={size}
      height={size}
      aria-label={`Capital allocation: ${(clampedFraction * 100).toFixed(1)}% at risk, ${((1 - clampedFraction) * 100).toFixed(1)}% available`}
      role="img"
    >
      <path d={safePath} fill="currentColor" className="text-profit/50" />
      <path d={riskPath} fill="currentColor" className="text-loss/60" />
      <circle cx={cx} cy={cy} r={r} fill="none" stroke="currentColor" strokeWidth="1" className="text-border-default" />
    </svg>
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

  const result = useMemo<SizingResult | null>(() => {
    const cap = parseFloat(capital);
    const rp = parseFloat(riskPct);
    const sl = parseFloat(slDistance);
    const ls = parseFloat(lotSize);

    let r: SizingResult | null = null;
    if (method === "fixedFractional") {
      r = calcFixedFractional(cap, rp, sl, ls);
    } else if (method === "kelly") {
      r = calcKelly(cap, parseFloat(winRate), parseFloat(rrRatio), sl, ls);
    } else {
      r = calcATR(cap, rp, parseFloat(atr), parseFloat(atrMult), ls);
    }

    if (r) track("trade", `position_sizing_calc_${method}`);
    return r;
  }, [method, capital, riskPct, slDistance, lotSize, winRate, rrRatio, atr, atrMult, track]);

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
            {/* Pie chart */}
            <div className="flex items-center gap-4 bg-surface-card border border-border-default rounded p-3">
              <PieChart atRiskFraction={result.capitalAtRisk} />
              <div className="flex-1 space-y-1">
                <div className="flex items-center gap-1.5 text-xxs">
                  <span className="w-2.5 h-2.5 rounded-sm bg-loss/60 inline-block shrink-0" />
                  <span className="text-text-muted">At Risk</span>
                  <span className="ml-auto font-mono font-semibold text-loss">
                    {(result.capitalAtRisk * 100).toFixed(2)}%
                  </span>
                </div>
                <div className="flex items-center gap-1.5 text-xxs">
                  <span className="w-2.5 h-2.5 rounded-sm bg-profit/50 inline-block shrink-0" />
                  <span className="text-text-muted">Available</span>
                  <span className="ml-auto font-mono font-semibold text-profit">
                    {((1 - result.capitalAtRisk) * 100).toFixed(2)}%
                  </span>
                </div>
              </div>
            </div>

            {/* Result rows */}
            <div className="bg-surface-card border border-border-default rounded p-2">
              <ResultRow label="Position Size (lots)" value={String(result.lots)} />
              <ResultRow label="Units (shares)" value={String(result.units)} />
              <ResultRow label="Rupee Risk" value={fmtINR(result.rupeeRisk)} accent="text-loss" />
              <ResultRow label="Max Loss" value={fmtINR(result.maxLoss)} accent="text-loss" />
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
