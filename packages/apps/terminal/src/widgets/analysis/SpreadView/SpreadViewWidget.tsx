/**
 * SpreadViewWidget — Vertical option spread builder and visualiser.
 *
 * Features:
 *   - Spread type selector: Bull Call, Bear Put, Bull Put, Bear Call
 *   - Inputs: underlying, long strike, short strike, net premium, lot size
 *   - Computed: max profit, max loss, breakeven, net premium, illustrative margin proxy
 *   - Payoff diagram: SVG line showing P&L at expiry vs underlying price
 *   - Deferred quick-execute button until a gated basket order route is wired
 */

import { useState, useMemo, memo, useCallback } from "react";
import { ArrowUpDown, ChevronDown } from "lucide-react";
import { FlintPayoffChart } from "@flinttrade/design-system";
import { useTrackBehavior } from "@/hooks/useTrackBehavior";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type SpreadType = "bull-call" | "bear-put" | "bull-put" | "bear-call";

export interface SpreadInputs {
  longStrike: number;
  shortStrike: number;
  premium: number; // positive = debit paid, negative = credit received
  lotSize: number;
}

export interface SpreadMetrics {
  maxProfit: number;
  maxLoss: number;
  breakeven: number;
  netPremium: number;
  illustrativeMarginProxy: number;
  isDebit: boolean;
}

export interface PayoffPoint {
  price: number;
  pnl: number;
}

export type SpreadAnalysis =
  | { valid: true; metrics: SpreadMetrics; payoff: PayoffPoint[] }
  | { valid: false; error: string };

// ---------------------------------------------------------------------------
// Spread definitions
// ---------------------------------------------------------------------------

const SPREAD_TYPES: { id: SpreadType; label: string; description: string }[] = [
  { id: "bull-call", label: "Bull Call",  description: "Buy lower call, sell higher call. Debit spread. Bullish." },
  { id: "bear-put",  label: "Bear Put",   description: "Buy higher put, sell lower put. Debit spread. Bearish." },
  { id: "bull-put",  label: "Bull Put",   description: "Sell higher put, buy lower put. Credit spread. Bullish." },
  { id: "bear-call", label: "Bear Call",  description: "Sell lower call, buy higher call. Credit spread. Bearish." },
];

const UNDERLYINGS = ["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX"];

// ---------------------------------------------------------------------------
// Defaults by spread type
// ---------------------------------------------------------------------------

const DEFAULTS: Record<SpreadType, Partial<SpreadInputs>> = {
  "bull-call": { longStrike: 24000, shortStrike: 24200, premium: 45, lotSize: 25 },
  "bear-put":  { longStrike: 23800, shortStrike: 23600, premium: 50, lotSize: 25 },
  "bull-put":  { longStrike: 23600, shortStrike: 23800, premium: -30, lotSize: 25 },
  "bear-call": { longStrike: 24200, shortStrike: 24000, premium: -35, lotSize: 25 },
};

// ---------------------------------------------------------------------------
// Metrics computation
// ---------------------------------------------------------------------------

function spreadWidth(type: SpreadType, inputs: SpreadInputs): number {
  return type === "bull-call" || type === "bull-put"
    ? inputs.shortStrike - inputs.longStrike
    : inputs.longStrike - inputs.shortStrike;
}

function validateSpreadInputs(type: SpreadType, inputs: SpreadInputs): string | null {
  const { longStrike, shortStrike, premium, lotSize } = inputs;
  if (
    !Number.isFinite(longStrike)
    || !Number.isFinite(shortStrike)
    || longStrike <= 0
    || shortStrike <= 0
  ) {
    return "Strikes must be finite positive numbers.";
  }

  if (!Number.isFinite(lotSize) || !Number.isInteger(lotSize) || lotSize <= 0) {
    return "Lot size must be a positive whole number.";
  }

  const longMustBeLower = type === "bull-call" || type === "bull-put";
  if (longMustBeLower ? longStrike >= shortStrike : longStrike <= shortStrike) {
    const spreadLabel = SPREAD_TYPES.find((spread) => spread.id === type)?.label ?? "This spread";
    const requiredOrder = longMustBeLower ? "below" : "above";
    return `${spreadLabel} requires the long strike ${requiredOrder} the short strike.`;
  }

  if (!Number.isFinite(premium)) {
    return "Net premium must be finite.";
  }

  const width = spreadWidth(type, inputs);
  const isDebit = type === "bull-call" || type === "bear-put";
  if (isDebit && (premium <= 0 || premium > width)) {
    return "Debit must be positive and no greater than the strike width.";
  }

  if (!isDebit && (premium >= 0 || -premium > width)) {
    return "Credit must be negative and no greater than the strike width.";
  }

  return null;
}

function computeMetrics(type: SpreadType, inputs: SpreadInputs): SpreadMetrics {
  const { longStrike, shortStrike, premium, lotSize } = inputs;
  const width = spreadWidth(type, inputs);
  const isDebit = type === "bull-call" || type === "bear-put";

  let maxProfit: number;
  let maxLoss: number;
  let breakeven: number;

  if (type === "bull-call") {
    maxProfit = (width - premium) * lotSize;
    maxLoss = premium * lotSize;
    breakeven = longStrike + premium;
  } else if (type === "bear-put") {
    maxProfit = (width - premium) * lotSize;
    maxLoss = premium * lotSize;
    breakeven = longStrike - premium;
  } else if (type === "bull-put") {
    const credit = -premium;
    maxProfit = credit * lotSize;
    maxLoss = (width - credit) * lotSize;
    breakeven = shortStrike - credit;
  } else {
    // bear-call
    const credit = -premium;
    maxProfit = credit * lotSize;
    maxLoss = (width - credit) * lotSize;
    breakeven = shortStrike + credit;
  }

  // Heuristic visual proxy only. Broker margin requires live contract and portfolio data.
  const illustrativeMarginProxy = isDebit ? maxLoss : maxLoss * 1.5;

  return {
    maxProfit,
    maxLoss,
    breakeven,
    netPremium: premium * lotSize,
    illustrativeMarginProxy,
    isDebit,
  };
}

function buildPayoff(type: SpreadType, inputs: SpreadInputs): PayoffPoint[] {
  const { longStrike, shortStrike, premium, lotSize } = inputs;
  const longIsLower = type === "bull-call" || type === "bull-put";
  const lowerStrike = longIsLower ? longStrike : shortStrike;
  const width = spreadWidth(type, inputs);
  const step = width / 20;
  const prices = Array.from({ length: 41 }, (_, i) => lowerStrike - width * 0.5 + i * step);

  return prices.map((price) => {
    let pnl: number;
    if (type === "bull-call") {
      const longPnl = Math.max(price - longStrike, 0);
      const shortPnl = -Math.max(price - shortStrike, 0);
      pnl = (longPnl + shortPnl - premium) * lotSize;
    } else if (type === "bear-put") {
      const longPnl = Math.max(longStrike - price, 0);
      const shortPnl = -Math.max(shortStrike - price, 0);
      pnl = (longPnl + shortPnl - premium) * lotSize;
    } else if (type === "bull-put") {
      const credit = -premium;
      const shortPnl = -Math.max(shortStrike - price, 0);
      const longPnl = Math.max(longStrike - price, 0);
      pnl = (credit + shortPnl + longPnl) * lotSize;
    } else {
      // bear-call
      const credit = -premium;
      const shortPnl = -Math.max(price - shortStrike, 0);
      const longPnl = Math.max(price - longStrike, 0);
      pnl = (credit + shortPnl + longPnl) * lotSize;
    }
    return { price, pnl };
  });
}

export function analyseSpread(type: SpreadType, inputs: SpreadInputs): SpreadAnalysis {
  const error = validateSpreadInputs(type, inputs);
  if (error) {
    return { valid: false, error };
  }

  return {
    valid: true,
    metrics: computeMetrics(type, inputs),
    payoff: buildPayoff(type, inputs),
  };
}

function buildPayoffChart(points: PayoffPoint[]) {
  const minPrice = points[0]?.price ?? 0;
  const maxPrice = points[points.length - 1]?.price ?? 1;
  const allPnls = points.map((p) => p.pnl);
  const minPnl = allPnls.length > 0 ? Math.min(...allPnls) : 0;
  const maxPnl = allPnls.length > 0 ? Math.max(...allPnls) : 1;
  const midPrice = (minPrice + maxPrice) / 2;

  return {
    points: points.map((point) => ({
      x: point.price,
      y: point.pnl,
      label: `${point.price.toLocaleString("en-IN")} ${point.pnl.toFixed(0)}`,
    })),
    xTicks: [minPrice, midPrice, maxPrice],
    yTicks: [minPnl, 0, maxPnl],
  };
}

// ---------------------------------------------------------------------------
// Metric display tile
// ---------------------------------------------------------------------------

interface MetricTileProps {
  label: string;
  value: string;
  colour?: string;
}

function MetricTile({ label, value, colour = "text-text-primary" }: MetricTileProps) {
  return (
    <div className="flex flex-col gap-0.5 bg-surface-hover rounded px-2 py-1.5 min-w-20">
      <span className="text-xxs leading-tight text-text-muted">{label}</span>
      <span className={`text-xs font-semibold font-mono tabular-nums ${colour}`}>{value}</span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Compact dropdown
// ---------------------------------------------------------------------------

interface CompactDropdownProps<T extends string> {
  value: T;
  options: { id: T; label: string }[];
  onChange: (v: T) => void;
  ariaLabel: string;
}

function CompactDropdown<T extends string>({ value, options, onChange, ariaLabel }: CompactDropdownProps<T>) {
  const [open, setOpen] = useState(false);
  const current = options.find((o) => o.id === value);
  return (
    <div className="relative">
      <button
        onClick={() => setOpen((p) => !p)}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-label={ariaLabel}
        className="flex items-center gap-1 px-2 py-1 text-xs font-medium text-text-primary bg-surface-hover border border-border-default rounded hover:border-accent/50 transition-colors"
      >
        <span>{current?.label ?? value}</span>
        <ChevronDown
          size={10}
          className={`transition-transform flex-none ${open ? "rotate-180" : ""}`}
          aria-hidden="true"
        />
      </button>
      {open && (
        <div
          className="absolute top-full left-0 mt-0.5 z-50 bg-surface-card border border-border-default rounded shadow-lg min-w-full"
          role="listbox"
          aria-label={ariaLabel}
        >
          {options.map((o) => (
            <button
              key={o.id}
              role="option"
              aria-selected={o.id === value}
              onClick={() => { onChange(o.id); setOpen(false); }}
              className={`block w-full text-left px-3 py-1.5 text-xs whitespace-nowrap hover:bg-surface-hover transition-colors ${
                o.id === value ? "text-accent" : "text-text-primary"
              }`}
            >
              {o.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Number input
// ---------------------------------------------------------------------------

interface NumberInputProps {
  label: string;
  value: number;
  onChange: (v: number) => void;
  step?: number;
}

function NumberInput({ label, value, onChange, step = 50 }: NumberInputProps) {
  return (
    <div className="flex flex-col gap-0.5">
      <label className="text-xxs text-text-muted">{label}</label>
      <input
        type="number"
        value={value}
        step={step}
        onChange={(e) => onChange(parseFloat(e.target.value) || 0)}
        aria-label={label}
        className="w-24 px-1.5 py-0.5 text-xs bg-surface-hover border border-border-default rounded text-text-primary focus:outline-none focus:border-accent/60 font-mono tabular-nums"
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main widget
// ---------------------------------------------------------------------------

function SpreadViewWidget() {
  const track = useTrackBehavior();

  const [spreadType, setSpreadType] = useState<SpreadType>("bull-call");
  const [underlying, setUnderlying] = useState("NIFTY");
  const [longStrike, setLongStrike] = useState(DEFAULTS["bull-call"].longStrike ?? 24000);
  const [shortStrike, setShortStrike] = useState(DEFAULTS["bull-call"].shortStrike ?? 24200);
  const [premium, setPremium] = useState(DEFAULTS["bull-call"].premium ?? 45);
  const [lotSize, setLotSize] = useState(DEFAULTS["bull-call"].lotSize ?? 25);

  const handleSpreadTypeChange = useCallback((t: SpreadType) => {
    setSpreadType(t);
    const d = DEFAULTS[t];
    setLongStrike(d.longStrike ?? 24000);
    setShortStrike(d.shortStrike ?? 24200);
    setPremium(d.premium ?? 0);
    track("trade", `spreadview_type_${t}`);
  }, [track]);

  const analysis = useMemo(
    () => analyseSpread(spreadType, { longStrike, shortStrike, premium, lotSize }),
    [spreadType, longStrike, shortStrike, premium, lotSize],
  );
  const payoffChart = useMemo(
    () => analysis.valid ? buildPayoffChart(analysis.payoff) : null,
    [analysis],
  );

  const spreadInfo = SPREAD_TYPES.find((s) => s.id === spreadType);

  return (
    <div className="h-full flex flex-col bg-surface-base overflow-hidden" aria-label="Options Spread View widget">

      {/* Header */}
      <div className="flex-none flex items-center gap-2 px-2 py-1.5 bg-surface-card border-b border-border-default">
        <ArrowUpDown size={13} className="text-accent shrink-0" aria-hidden="true" />
        <span className="text-xs font-semibold text-text-primary">Spread View</span>
        <span
          className="px-1.5 py-0.5 text-xxs bg-warning/10 text-warning border border-warning/30 rounded"
          role="status"
          title="The inputs and calculations are illustrative, not live option-chain or broker-margin data."
        >
          Illustrative inputs
        </span>
        <div className="flex-1" />
        {/* Spread type selector */}
        <CompactDropdown
          value={spreadType}
          options={SPREAD_TYPES.map((s) => ({ id: s.id, label: s.label }))}
          onChange={handleSpreadTypeChange}
          ariaLabel="Select spread type"
        />
      </div>

      <div className="flex-1 min-h-0 overflow-y-auto px-2 py-2 flex flex-col gap-2">

        {/* Description */}
        {spreadInfo && (
          <p className="text-xxs text-text-muted italic">{spreadInfo.description}</p>
        )}

        {/* Inputs row */}
        <div className="flex items-end gap-2 flex-wrap">
          {/* Underlying */}
          <div className="flex flex-col gap-0.5">
            <label className="text-xxs text-text-muted">Underlying</label>
            <CompactDropdown
              value={underlying}
              options={UNDERLYINGS.map((u) => ({ id: u, label: u }))}
              onChange={(v) => setUnderlying(v)}
              ariaLabel="Select underlying"
            />
          </div>

          <NumberInput label="Long Strike" value={longStrike} onChange={setLongStrike} step={50} />
          <NumberInput label="Short Strike" value={shortStrike} onChange={setShortStrike} step={50} />
          <NumberInput label="Net Premium" value={premium} onChange={setPremium} step={1} />
          <NumberInput label="Lot Size" value={lotSize} onChange={setLotSize} step={1} />
        </div>

        {!analysis.valid && (
          <div
            role="alert"
            className="rounded border border-loss/30 bg-loss/10 px-2 py-1.5 text-xs text-loss"
          >
            Invalid inputs: {analysis.error}
          </div>
        )}

        {analysis.valid && payoffChart && (
          <>
            {/* Metrics */}
            <section aria-labelledby="spread-metrics-label">
              <p id="spread-metrics-label" className="text-xxs font-medium text-text-muted mb-1 uppercase tracking-wide">
                Spread Metrics
              </p>
              <div className="flex flex-wrap gap-1.5">
                <MetricTile
                  label="Max Profit"
                  value={`₹${analysis.metrics.maxProfit.toLocaleString("en-IN")}`}
                  colour="text-profit"
                />
                <MetricTile
                  label="Max Loss"
                  value={`₹${analysis.metrics.maxLoss.toLocaleString("en-IN")}`}
                  colour="text-loss"
                />
                <MetricTile
                  label="Breakeven"
                  value={analysis.metrics.breakeven.toLocaleString("en-IN")}
                />
                <MetricTile
                  label="Net Premium"
                  value={`₹${Math.abs(analysis.metrics.netPremium).toLocaleString("en-IN")} ${analysis.metrics.isDebit ? "Dr" : "Cr"}`}
                  colour={analysis.metrics.isDebit ? "text-loss" : "text-profit"}
                />
                <MetricTile
                  label="Illustrative margin proxy"
                  value={`₹${analysis.metrics.illustrativeMarginProxy.toLocaleString("en-IN")}`}
                  colour="text-warning"
                />
              </div>
              <p className="mt-1 text-xxs text-text-muted">Heuristic only; not broker margin.</p>
            </section>

            {/* Payoff diagram */}
            <section aria-labelledby="payoff-label">
              <p id="payoff-label" className="text-xxs font-medium text-text-muted mb-1 uppercase tracking-wide">
                Payoff at Expiry
              </p>
              <FlintPayoffChart
                ariaLabel="Spread payoff diagram"
                points={payoffChart.points}
                breakeven={analysis.metrics.breakeven}
                xTicks={payoffChart.xTicks}
                yTicks={payoffChart.yTicks}
                xFormatter={(value) => value.toLocaleString("en-IN")}
                yFormatter={(value) => (
                  value >= 1000 ? `${(value / 1000).toFixed(0)}k` : value >= 0 ? `+${value.toFixed(0)}` : `${value.toFixed(0)}`
                )}
                width={500}
                height={140}
              />
              <div className="flex items-center gap-3 mt-1 flex-wrap text-xxs">
                <div className="flex items-center gap-1">
                  <span className="inline-block w-6 h-px bg-profit/60" />
                  <span className="text-text-muted">Profit zone</span>
                </div>
                <div className="flex items-center gap-1">
                  <span className="inline-block w-6 h-px bg-loss/60" />
                  <span className="text-text-muted">Loss zone</span>
                </div>
                <div className="flex items-center gap-1">
                  <span className="inline-block w-3 border-t border-dashed border-warning/70" />
                  <span className="text-text-muted">
                    Breakeven: {analysis.metrics.breakeven.toLocaleString("en-IN")}
                  </span>
                </div>
              </div>
            </section>
          </>
        )}

        {/* Execute button */}
        <div className="flex items-center gap-3 pt-1">
          <button
            disabled
            aria-label={`Execute ${spreadInfo?.label ?? "spread"} spread unavailable`}
            title="This builder is not wired to gated basket execution."
            className="px-3 py-1.5 text-xs font-medium bg-accent/90 hover:bg-accent text-white rounded disabled:opacity-40 transition-colors"
          >
            Execution not wired
          </button>
          <span className="text-xxs text-text-muted">
            This builder is not wired to gated basket execution
          </span>
        </div>
      </div>
    </div>
  );
}

export default memo(SpreadViewWidget);
