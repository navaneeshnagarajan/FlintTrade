// ─── Scalper — control bar (symbol, expiry, strikes, lots, order settings) ────

import { AlertTriangle, RefreshCw, Zap, ZapOff } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { NumberInput, Stepper, StatusPill, ToggleGroup } from "./ScalperPrimitives";
import type { IntervalValue, OrderTypeValue, ProductType, StatusState } from "./types";
import { SYMBOLS } from "./types";

export interface ScalperControlsProps {
  // Row 1
  symbol: string;
  onSymbolChange: (v: string) => void;
  expiries: string[];
  expiriesError: boolean;
  expiry: string;
  onExpiryChange: (v: string) => void;
  onRetryExpiries: () => void;
  ceStrike: number | null;
  onCeOffsetDec: () => void;
  onCeOffsetInc: () => void;
  peStrike: number | null;
  onPeOffsetDec: () => void;
  onPeOffsetInc: () => void;
  status: StatusState;
  focused: boolean;

  // Row 2
  lots: number;
  lotSize: number;
  /** False until the backend confirms the lot size — orders stay blocked. */
  lotSizeVerified: boolean;
  onLotsDec: () => void;
  onLotsInc: () => void;
  product: ProductType;
  onProductChange: (v: ProductType) => void;
  orderType: OrderTypeValue;
  onOrderTypeChange: (v: OrderTypeValue) => void;
  /** Limit price — required (and shown) only when orderType is LIMIT. */
  limitPrice: string;
  onLimitPriceChange: (v: string) => void;
  /**
   * Optional stop-loss distance in points. When set, the order goes through
   * the gated bracket endpoint as entry + a real SL exit leg. Blank = off.
   */
  slPoints: string;
  onSlPointsChange: (v: string) => void;
  /**
   * Optional target distance in points. When set, the order goes through
   * the gated bracket endpoint as entry + a real target exit leg. Blank =
   * off. Mutually exclusive with SL points (no OCO fill monitor yet).
   */
  targetPoints: string;
  onTargetPointsChange: (v: string) => void;
  interval: IntervalValue;
  onIntervalChange: (v: IntervalValue) => void;
  oneClick: boolean;
  onOneClickToggle: () => void;
}

export function ScalperControls({
  symbol,
  onSymbolChange,
  expiries,
  expiriesError,
  expiry,
  onExpiryChange,
  onRetryExpiries,
  ceStrike,
  onCeOffsetDec,
  onCeOffsetInc,
  peStrike,
  onPeOffsetDec,
  onPeOffsetInc,
  status,
  focused,
  lots,
  lotSize,
  lotSizeVerified,
  onLotsDec,
  onLotsInc,
  product,
  onProductChange,
  orderType,
  onOrderTypeChange,
  limitPrice,
  onLimitPriceChange,
  slPoints,
  onSlPointsChange,
  targetPoints,
  onTargetPointsChange,
  interval,
  onIntervalChange,
  oneClick,
  onOneClickToggle,
}: ScalperControlsProps) {
  return (
    <div className="shrink-0 bg-surface-card border-b border-border-default">
      {/* Row 1: Index, Expiry, CE Strike, PE Strike, Status */}
      <div className="flex items-end gap-3 px-3 py-2 flex-wrap">
        {/* Index selector */}
        <div className="flex flex-col gap-0.5">
          <span className="text-xxs text-text-muted uppercase tracking-wider font-sans">Index</span>
          <Select value={symbol} onValueChange={onSymbolChange}>
            <SelectTrigger size="sm" className="font-mono font-bold min-w-[9rem]">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {SYMBOLS.map((s) => (
                <SelectItem key={s} value={s} className="font-mono font-bold">{s}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        {/* Expiry selector */}
        <div className="flex flex-col gap-0.5">
          <span className="text-xxs text-text-muted uppercase tracking-wider font-sans">Expiry</span>
          {expiriesError ? (
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={onRetryExpiries}
              className="h-8 flex items-center gap-1.5 px-2 text-xs font-mono text-loss border-loss/30 bg-loss/5 hover:bg-loss/10 transition-colors"
            >
              <AlertTriangle size={10} />
              Failed to load
              <RefreshCw size={10} />
            </Button>
          ) : (
            <Select
              value={expiry}
              onValueChange={onExpiryChange}
              disabled={expiries.length === 0}
            >
              <SelectTrigger size="sm" className="font-mono font-bold min-w-[9rem]">
                <SelectValue placeholder={expiries.length === 0 ? "Loading…" : "Select expiry"} />
              </SelectTrigger>
              <SelectContent>
                {expiries.map((ex) => (
                  <SelectItem key={ex} value={ex} className="font-mono">{ex}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          )}
        </div>

        {/* CE Strike stepper */}
        <Stepper
          label="CE Strike"
          value={ceStrike != null ? `${ceStrike}` : "—"}
          onDec={onCeOffsetDec}
          onInc={onCeOffsetInc}
        />

        {/* PE Strike stepper */}
        <Stepper
          label="PE Strike"
          value={peStrike != null ? `${peStrike}` : "—"}
          onDec={onPeOffsetDec}
          onInc={onPeOffsetInc}
        />

        <div className="flex-1" />

        {/* Status pill */}
        <StatusPill message={status.message} type={status.type} />

        {/* Keyboard hint */}
        {focused && (
          <span className="text-xxs text-text-disabled border border-border-subtle rounded-md px-1.5 py-1 hidden lg:inline-flex items-center font-mono">
            Shift + Arrows to trade
          </span>
        )}
      </div>

      {/* Row 2: Lots, Product, OrderType, Limit price, SL/Target points,
          Interval, One-click. The SL/Target inputs are RESTORED now that
          they place a real protective exit leg through the gated bracket
          endpoint (POST /api/v1/orders/bracket) — an earlier incarnation
          displayed them without sending anything, which was silent-risk
          theatre and got them removed. */}
      <div className="flex items-end gap-3 px-3 py-2 border-t border-border-subtle flex-wrap">
        {/* Lot spinner — large. Unverified lot sizes block orders (fail closed). */}
        <Stepper
          label="Lot"
          sublabel={lotSizeVerified ? `×${lotSize}` : `×${lotSize} (unverified)`}
          value={`${lots} (${lots * lotSize})`}
          onDec={onLotsDec}
          onInc={onLotsInc}
          large
        />

        {/* Product toggle */}
        <ToggleGroup
          label="Product"
          value={product}
          options={["MIS", "NRML"] as const}
          onChange={(v) => onProductChange(v as ProductType)}
        />

        {/* Order type toggle */}
        <ToggleGroup
          label="Type"
          value={orderType}
          options={["MARKET", "LIMIT"] as const}
          onChange={(v) => onOrderTypeChange(v as OrderTypeValue)}
        />

        {/* Limit price — required for LIMIT orders (₹0 limits are rejected) */}
        {orderType === "LIMIT" && (
          <NumberInput
            label="Limit ₹"
            value={limitPrice}
            onChange={onLimitPriceChange}
            min={0}
            placeholder="0.00"
          />
        )}

        {/* Optional protective exit leg, in points from the entry price.
            Leave both blank for a plain order; enter EXACTLY ONE to place a
            gated bracket (entry + SL or target leg). Both together are
            refused — there is no OCO fill monitor to cancel the sibling. */}
        <NumberInput
          label="SL pts"
          value={slPoints}
          onChange={onSlPointsChange}
          min={0}
          placeholder="off"
          ariaLabel="Stop-loss points"
        />
        <NumberInput
          label="Target pts"
          value={targetPoints}
          onChange={onTargetPointsChange}
          min={0}
          placeholder="off"
          ariaLabel="Target points"
        />

        {/* Timeframe buttons */}
        <ToggleGroup
          label="Timeframe"
          value={interval}
          options={["1m", "3m", "5m", "15m"] as const}
          onChange={(v) => onIntervalChange(v as IntervalValue)}
        />

        <div className="flex-1" />

        {/* 1-CLICK toggle */}
        <div className="flex flex-col gap-0.5">
          <span className="text-xxs text-text-muted uppercase tracking-wider font-sans">Mode</span>
          <Button
            type="button"
            variant={oneClick ? "default" : "outline"}
            size="sm"
            onClick={onOneClickToggle}
            title={oneClick ? "One-click ON — click to disable" : "One-click OFF — click to enable"}
            className={`flex items-center gap-1.5 px-4 h-8 font-semibold text-sm transition-colors ${
              oneClick
                ? "bg-accent text-white shadow-sm hover:bg-accent/90"
                : "bg-surface-hover border-border-default text-text-muted hover:text-text-primary"
            }`}
          >
            {oneClick ? <Zap size={14} /> : <ZapOff size={14} />}
            {oneClick ? "1-CLICK ON" : "1-CLICK"}
          </Button>
        </div>
      </div>
    </div>
  );
}
