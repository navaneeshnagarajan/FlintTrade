/**
 * SpreadViewWidget — Vertical option spread builder and visualiser.
 *
 * Features:
 *   - Spread type selector: Bull Call, Bear Put, Bull Put, Bear Call
 *   - Inputs: underlying, expiry, long strike, short strike
 *   - Computed: max profit, max loss, breakeven, net premium, margin required
 *   - Payoff diagram: SVG line showing P&L at expiry vs underlying price
 *   - Deferred quick-execute button until a gated basket order route is wired
 */

import { useState, useMemo, memo, useCallback } from "react";
import { ArrowUpDown, ChevronDown } from "lucide-react";
import { FlintPayoffChart } from "@flinttrade/design-system";
import { useBrokerConnected } from "@/hooks/useBrokerConnected";
import { useTrackBehavior } from "@/hooks/useTrackBehavior";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type SpreadType = "bull-call" | "bear-put" | "bull-put" | "bear-call";

interface SpreadInputs {
  underlying: string;
  expiry: string;
  longStrike: number;
  shortStrike: number;
  premium: number;    // net premium paid/received (positive = paid, negative = received)
  lotSize: number;
}

interface SpreadMetrics {
  maxProfit: number;
  maxLoss: number;
  breakeven: number;
  netPremium: number;
  marginRequired: number;
  isDebit: boolean;    // true = debit spread (pay premium), false = credit
}

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
const EXPIRIES = ["24APR2026", "01MAY2026", "08MAY2026", "29MAY2026"];

// ---------------------------------------------------------------------------
// Defaults by spread type
// ---------------------------------------------------------------------------

const DEFAULTS: Record<SpreadType, Partial<SpreadInputs>> = {
  "bull-call": { longStrike: 24000, shortStrike: 24200, premium: 45, lotSize: 25 },
  "bear-put":  { longStrike: 23800, shortStrike: 23600, premium: 50, lotSize: 25 },
  "bull-put":  { longStrike: 23800, shortStrike: 23600, premium: -30, lotSize: 25 },
  "bear-call": { longStrike: 24000, shortStrike: 24200, premium: -35, lotSize: 25 },
};

// ---------------------------------------------------------------------------
// Metrics computation
// ---------------------------------------------------------------------------

function computeMetrics(type: SpreadType, inputs: SpreadInputs): SpreadMetrics {
  const { longStrike, shortStrike, premium, lotSize } = inputs;
  const width = Math.abs(shortStrike - longStrike);
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
    const credit = Math.abs(premium);
    maxProfit = credit * lotSize;
    maxLoss = (width - credit) * lotSize;
    breakeven = shortStrike - credit;
  } else {
    // bear-call
    const credit = Math.abs(premium);
    maxProfit = credit * lotSize;
    maxLoss = (width - credit) * lotSize;
    breakeven = longStrike + credit;
  }

  // Rough margin: max loss for debit, 1.5x max loss for credit
  const marginRequired = isDebit ? maxLoss : maxLoss * 1.5;

  return {
    maxProfit,
    maxLoss,
    breakeven,
    netPremium: premium * lotSize,
    marginRequired,
    isDebit,
  };
}

interface PayoffPoint {
  price: number;
  pnl: number;
}

function buildPayoff(type: SpreadType, inputs: SpreadInputs): PayoffPoint[] {
  const { longStrike, shortStrike, premium, lotSize } = inputs;
  const width = Math.abs(shortStrike - longStrike);
  const lo = Math.min(longStrike, shortStrike);
  const hi = Math.max(longStrike, shortStrike);
  const step = width / 20;
  const prices = Array.from({ length: 41 }, (_, i) => lo - width * 0.5 + i * step);

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
      const credit = Math.abs(premium);
      const shortPnl = -Math.max(hi - price, 0);
      const longPnl = Math.max(lo - price, 0);
      pnl = (credit + shortPnl + longPnl) * lotSize;
    } else {
      // bear-call
      const credit = Math.abs(premium);
      const shortPnl = -Math.max(price - lo, 0);
      const longPnl = Math.max(price - hi, 0);
      pnl = (credit + shortPnl + longPnl) * lotSize;
    }
    return { price, pnl };
  });
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
      <span className="text-xxs text-text-muted whitespace-nowrap">{label}</span>
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
  const isConnected = useBrokerConnected();
  const track = useTrackBehavior();

  const [spreadType, setSpreadType] = useState<SpreadType>("bull-call");
  const [underlying, setUnderlying] = useState("NIFTY");
  const [expiry, setExpiry] = useState(EXPIRIES[0]);
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

  const inputs: SpreadInputs = { underlying, expiry, longStrike, shortStrike, premium, lotSize };

  const metrics = useMemo(() => computeMetrics(spreadType, inputs), [spreadType, inputs]);

  const payoff = useMemo(() => buildPayoff(spreadType, inputs), [spreadType, inputs]);
  const payoffChart = useMemo(() => buildPayoffChart(payoff), [payoff]);

  const spreadInfo = SPREAD_TYPES.find((s) => s.id === spreadType);

  return (
    <div className="h-full flex flex-col bg-surface-base overflow-hidden" aria-label="Options Spread View widget">

      {/* Header */}
      <div className="flex-none flex items-center gap-2 px-2 py-1.5 bg-surface-card border-b border-border-default">
        <ArrowUpDown size={13} className="text-accent shrink-0" aria-hidden="true" />
        <span className="text-xs font-semibold text-text-primary">Spread View</span>
        {!isConnected && (
          <span className="px-1.5 py-0.5 text-xxs bg-warning/10 text-warning border border-warning/30 rounded">
            Sample
          </span>
        )}
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

          {/* Expiry */}
          <div className="flex flex-col gap-0.5">
            <label className="text-xxs text-text-muted">Expiry</label>
            <CompactDropdown
              value={expiry}
              options={EXPIRIES.map((e) => ({ id: e, label: e }))}
              onChange={(v) => setExpiry(v)}
              ariaLabel="Select expiry"
            />
          </div>

          <NumberInput label="Long Strike" value={longStrike} onChange={setLongStrike} step={50} />
          <NumberInput label="Short Strike" value={shortStrike} onChange={setShortStrike} step={50} />
          <NumberInput label="Net Premium" value={premium} onChange={setPremium} step={1} />
          <NumberInput label="Lot Size" value={lotSize} onChange={setLotSize} step={1} />
        </div>

        {/* Metrics */}
        <section aria-labelledby="spread-metrics-label">
          <p id="spread-metrics-label" className="text-xxs font-medium text-text-muted mb-1 uppercase tracking-wide">
            Spread Metrics
          </p>
          <div className="flex flex-wrap gap-1.5">
            <MetricTile
              label="Max Profit"
              value={`₹${metrics.maxProfit.toLocaleString("en-IN")}`}
              colour="text-profit"
            />
            <MetricTile
              label="Max Loss"
              value={`₹${metrics.maxLoss.toLocaleString("en-IN")}`}
              colour="text-loss"
            />
            <MetricTile
              label="Breakeven"
              value={metrics.breakeven.toLocaleString("en-IN")}
            />
            <MetricTile
              label="Net Premium"
              value={`₹${Math.abs(metrics.netPremium).toLocaleString("en-IN")} ${metrics.isDebit ? "Dr" : "Cr"}`}
              colour={metrics.isDebit ? "text-loss" : "text-profit"}
            />
            <MetricTile
              label="Margin Req."
              value={`₹${metrics.marginRequired.toLocaleString("en-IN")}`}
              colour="text-warning"
            />
          </div>
        </section>

        {/* Payoff diagram */}
        <section aria-labelledby="payoff-label">
          <p id="payoff-label" className="text-xxs font-medium text-text-muted mb-1 uppercase tracking-wide">
            Payoff at Expiry
          </p>
          <FlintPayoffChart
            ariaLabel="Spread payoff diagram"
            points={payoffChart.points}
            breakeven={metrics.breakeven}
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
              <span className="text-text-muted">Breakeven: {metrics.breakeven.toLocaleString("en-IN")}</span>
            </div>
          </div>
        </section>

        {/* Execute button */}
        <div className="flex items-center gap-3 pt-1">
          <button
            disabled
            aria-label={`Execute ${spreadInfo?.label ?? "spread"} spread unavailable`}
            title="Basket execution is not wired yet."
            className="px-3 py-1.5 text-xs font-medium bg-accent/90 hover:bg-accent text-white rounded disabled:opacity-40 transition-colors"
          >
            Execution not wired
          </button>
          {!isConnected && (
            <span className="text-xxs text-text-muted">Connect broker to execute</span>
          )}
          {isConnected && (
            <span className="text-xxs text-text-muted">Basket execution not wired yet</span>
          )}
        </div>
      </div>
    </div>
  );
}

export default memo(SpreadViewWidget);
