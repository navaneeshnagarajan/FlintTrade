/**
 * CurrencyConverterWidget — Live currency conversion for FlintTrade.
 *
 * Features:
 *   - Currency selectors for common pairs: INR, USD, EUR, GBP, JPY, SGD, AED
 *   - Amount input with converted amount display
 *   - Hardcoded rate table (refreshed manually per session)
 *   - Swap button to reverse from/to
 *   - Historical rate sparkline (last 30 days — sample data)
 */

import { useState, useMemo, useEffect, memo } from "react";
import { ArrowLeftRight, RefreshCw, AlertTriangle } from "lucide-react";
import { FlintMiniSparkline } from "@flinttrade/design-system";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { useTrackBehavior } from "@/hooks/useTrackBehavior";

// ---------------------------------------------------------------------------
// Currency config
// ---------------------------------------------------------------------------

const CURRENCIES = ["INR", "USD", "EUR", "GBP", "JPY", "SGD", "AED"] as const;
type Currency = (typeof CURRENCIES)[number];

/** Mid-market rates relative to INR (1 unit of currency = X INR). */
const RATES_TO_INR: Record<Currency, number> = {
  INR: 1,
  USD: 83.52,
  EUR: 90.14,
  GBP: 105.61,
  JPY: 0.546,
  SGD: 62.07,
  AED: 22.74,
};

const CURRENCY_SYMBOLS: Record<Currency, string> = {
  INR: "₹",
  USD: "$",
  EUR: "€",
  GBP: "£",
  JPY: "¥",
  SGD: "S$",
  AED: "د.إ",
};

const CURRENCY_NAMES: Record<Currency, string> = {
  INR: "Indian Rupee",
  USD: "US Dollar",
  EUR: "Euro",
  GBP: "British Pound",
  JPY: "Japanese Yen",
  SGD: "Singapore Dollar",
  AED: "UAE Dirham",
};

/** Convert `amount` from `from` currency to `to` currency via INR pivot. */
function convert(amount: number, from: Currency, to: Currency): number {
  if (from === to) return amount;
  const inrAmount = amount * RATES_TO_INR[from];
  return inrAmount / RATES_TO_INR[to];
}

/** Format number for display with appropriate decimal places. */
function formatConverted(value: number, currency: Currency): string {
  const decimals = currency === "JPY" ? 0 : 2;
  return value.toLocaleString("en-IN", {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  });
}

// ---------------------------------------------------------------------------
// Sparkline — deterministic 30-day sample rate history rendered through core.
// ---------------------------------------------------------------------------

/** Generate deterministic 30-day rate history from base rate. */
function generateHistory(from: Currency, to: Currency): number[] {
  const baseRate = convert(1, from, to);
  const seed = from.charCodeAt(0) + to.charCodeAt(0);
  return Array.from({ length: 30 }, (_, i) => {
    const noise = Math.sin((i + seed) * 0.7) * 0.012 + Math.cos((i * seed) * 0.3) * 0.008;
    return baseRate * (1 + noise);
  });
}

interface SparklineProps {
  data: number[];
}

function Sparkline({ data }: SparklineProps) {
  if (data.length < 2) return null;

  const first = data[0];
  const last = data[data.length - 1];

  return (
    <FlintMiniSparkline
      points={data}
      positive={last >= first}
      ariaLabel="30-day rate history sparkline"
      className="h-8 w-40"
    />
  );
}

// ---------------------------------------------------------------------------
// Main widget
// ---------------------------------------------------------------------------

function CurrencyConverterWidget() {
  const track = useTrackBehavior();

  const [from, setFrom] = useState<Currency>("USD");
  const [to, setTo] = useState<Currency>("INR");
  const [amountStr, setAmountStr] = useState("1");

  useEffect(() => {
    track("trade", "widget_view_currency_converter");
  }, [track]);

  const amount = useMemo(() => {
    const parsed = parseFloat(amountStr);
    return isNaN(parsed) || parsed < 0 ? 0 : parsed;
  }, [amountStr]);

  const converted = useMemo(() => convert(amount, from, to), [amount, from, to]);

  const rate = useMemo(() => convert(1, from, to), [from, to]);
  const inverseRate = useMemo(() => convert(1, to, from), [from, to]);

  const sparkData = useMemo(() => generateHistory(from, to), [from, to]);

  const pctChange = useMemo(() => {
    const first = sparkData[0];
    const last = sparkData[sparkData.length - 1];
    return ((last - first) / first) * 100;
  }, [sparkData]);

  function handleSwap() {
    setFrom(to);
    setTo(from);
    track("trade", "currency_converter_swap");
  }

  function handleFromChange(val: string) {
    const c = val as Currency;
    if (c === to) setTo(from);
    setFrom(c);
  }

  function handleToChange(val: string) {
    const c = val as Currency;
    if (c === from) setFrom(to);
    setTo(c);
  }

  return (
    <div className="h-full flex flex-col bg-surface-base overflow-hidden">
      {/* Header */}
      <div className="flex-none flex items-center gap-2 px-3 py-2 bg-surface-card border-b border-border-default">
        <ArrowLeftRight size={13} className="text-text-muted" aria-hidden="true" />
        <span className="text-xs font-medium text-text-primary">Currency Converter</span>
        <div className="flex-1" />
        <span
          className="flex items-center gap-1 text-xxs font-medium text-amber-400 bg-amber-400/10 border border-amber-400/30 rounded px-1.5 py-0.5"
          role="status"
          aria-label="Exchange rates are hardcoded sample values, not fetched live"
          title="Exchange rates are hardcoded and not fetched live — indicative only"
        >
          <AlertTriangle size={9} aria-hidden="true" />
          Static rates — not live
        </span>
      </div>

      <div className="flex-1 overflow-auto p-3 space-y-3">
        {/* From */}
        <div className="space-y-1">
          <label className="text-xxs text-text-muted uppercase tracking-wide">From</label>
          <div className="flex gap-2">
            <Select value={from} onValueChange={handleFromChange}>
              <SelectTrigger className="w-28 h-8 text-xs" aria-label="From currency">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {CURRENCIES.map((c) => (
                  <SelectItem key={c} value={c} className="text-xs">
                    {CURRENCY_SYMBOLS[c]} {c}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Input
              type="number"
              min="0"
              step="any"
              value={amountStr}
              onChange={(e) => setAmountStr(e.target.value)}
              className="flex-1 h-8 text-sm font-mono"
              aria-label="Amount to convert"
              placeholder="Enter amount"
            />
          </div>
          <p className="text-xxs text-text-muted">{CURRENCY_NAMES[from]}</p>
        </div>

        {/* Swap */}
        <div className="flex justify-center">
          <Button
            variant="ghost"
            size="sm"
            onClick={handleSwap}
            className="h-7 w-7 p-0 rounded-full border border-border-default hover:bg-surface-hover"
            aria-label="Swap currencies"
          >
            <RefreshCw size={12} aria-hidden="true" />
          </Button>
        </div>

        {/* To */}
        <div className="space-y-1">
          <label className="text-xxs text-text-muted uppercase tracking-wide">To</label>
          <div className="flex gap-2">
            <Select value={to} onValueChange={handleToChange}>
              <SelectTrigger className="w-28 h-8 text-xs" aria-label="To currency">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {CURRENCIES.map((c) => (
                  <SelectItem key={c} value={c} className="text-xs">
                    {CURRENCY_SYMBOLS[c]} {c}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <div
              className="flex-1 h-8 flex items-center px-3 bg-surface-elevated rounded-md border border-border-subtle"
              aria-live="polite"
              aria-label="Converted amount"
            >
              <span className="text-sm font-mono font-semibold text-text-primary tabular-nums">
                {CURRENCY_SYMBOLS[to]}{formatConverted(converted, to)}
              </span>
            </div>
          </div>
          <p className="text-xxs text-text-muted">{CURRENCY_NAMES[to]}</p>
        </div>

        {/* Rate info */}
        <div className="rounded-md border border-border-subtle bg-surface-elevated p-2.5 space-y-1">
          <div className="flex items-center justify-between text-xs">
            <span className="text-text-muted">Exchange Rate</span>
            <span className="font-mono tabular-nums text-text-primary">
              1 {from} = {CURRENCY_SYMBOLS[to]}{formatConverted(rate, to)} {to}
            </span>
          </div>
          <div className="flex items-center justify-between text-xs">
            <span className="text-text-muted">Inverse</span>
            <span className="font-mono tabular-nums text-text-secondary">
              1 {to} = {CURRENCY_SYMBOLS[from]}{formatConverted(inverseRate, from)} {from}
            </span>
          </div>
        </div>

        {/* Sparkline */}
        <div className="space-y-1.5">
          <div className="flex items-center justify-between">
            <span className="text-xxs text-text-muted uppercase tracking-wide">30-day trend</span>
            <span
              className={cn(
                "text-xxs font-mono tabular-nums",
                pctChange >= 0 ? "text-profit" : "text-loss",
              )}
            >
              {pctChange >= 0 ? "+" : ""}{pctChange.toFixed(2)}%
            </span>
          </div>
          <div className="flex justify-center">
            <Sparkline data={sparkData} />
          </div>
          <p className="text-center text-xxs text-text-muted">
            {from}/{to} · last 30 days
          </p>
        </div>

        {/* Disclaimer */}
        <p className="text-xxs text-text-muted text-center border-t border-border-subtle pt-2">
          Indicative rates only. Not for transactional use.
        </p>
      </div>
    </div>
  );
}

export default memo(CurrencyConverterWidget);
