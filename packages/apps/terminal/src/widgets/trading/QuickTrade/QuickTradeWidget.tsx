/**
 * QuickTradeWidget — Ultra-compact one-click order entry for scalpers.
 *
 * Features:
 *   - Symbol + exchange from panel params, falling back to the workspace's
 *     selected instrument (Watchlist selection), then NIFTY/NSE
 *   - Large BUY / SELL buttons side by side
 *   - Quantity lot presets: 1, 2, 5, 10 — sized by the instrument's REAL lot
 *     size (quantity = lots × lot size, fetched via getSymbol)
 *   - Fail-closed on derivative exchanges: no order is sent until the lot
 *     size has been confirmed from the backend
 *   - Product type toggle: MIS / NRML / CNC
 *   - Order type selector: MARKET / LIMIT
 *   - Optional limit price input (LIMIT mode only)
 *   - Fires placeOrder from @/services/api (gated backend route)
 *   - Confirm dialog for orders of 10+ lots
 */

import { useState, useCallback, useEffect, memo } from "react";
import { useAtomValue } from "jotai";
import { Zap, CheckCircle2, AlertCircle, Loader2, MousePointerClick } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { placeOrder, getSymbol } from "@/services/api";
import { selectedSymbolAtom } from "@/atoms/marketAtoms";
import { useModeStore } from "@/stores/modeStore";
import { useTrackBehavior } from "@/hooks/useTrackBehavior";
import type { WidgetProps } from "@/types/widgets";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const LOT_PRESETS = [1, 2, 5, 10] as const;
type LotPreset = (typeof LOT_PRESETS)[number];

const PRODUCT_TYPES = ["MIS", "NRML", "CNC"] as const;
type ProductType = (typeof PRODUCT_TYPES)[number];

const ORDER_TYPES = ["MARKET", "LIMIT"] as const;
type OrderType = (typeof ORDER_TYPES)[number];

/** Orders of this many lots or more require confirmation. */
const LARGE_ORDER_THRESHOLD = 10;

/** Exchanges where contracts trade in lots — a real lot size is mandatory. */
const DERIVATIVE_EXCHANGES = new Set(["NFO", "BFO", "MCX", "CDS", "BCD"]);

// ---------------------------------------------------------------------------
// Pill selector component
// ---------------------------------------------------------------------------

interface PillGroupProps<T extends string> {
  label: string;
  options: readonly T[];
  value: T;
  onChange: (v: T) => void;
}

function PillGroup<T extends string>({ label, options, value, onChange }: PillGroupProps<T>) {
  return (
    <div className="space-y-1">
      <div className="text-xxs text-text-muted uppercase tracking-wide">{label}</div>
      <div className="flex gap-1" role="group" aria-label={label}>
        {options.map((opt) => (
          <button
            key={opt}
            onClick={() => onChange(opt)}
            aria-pressed={opt === value}
            className={`flex-1 px-1.5 py-1 text-xs font-medium rounded border transition-colors ${
              opt === value
                ? "bg-accent/15 text-accent border-accent/40"
                : "text-text-secondary border-border-default hover:bg-surface-hover hover:text-text-primary"
            }`}
          >
            {opt}
          </button>
        ))}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Status banner
// ---------------------------------------------------------------------------

type Status = { type: "success"; message: string } | { type: "error"; message: string } | null;

function StatusBanner({ status }: { status: Status }) {
  if (!status) return null;
  const isSuccess = status.type === "success";
  return (
    <div
      role="status"
      aria-live="polite"
      className={`flex items-center gap-1.5 px-2 py-1.5 text-xs rounded border ${
        isSuccess
          ? "bg-profit/10 text-profit border-profit/30"
          : "bg-loss/10 text-loss border-loss/30"
      }`}
    >
      {isSuccess ? <CheckCircle2 size={11} aria-hidden="true" /> : <AlertCircle size={11} aria-hidden="true" />}
      {status.message}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Confirm dialog (simple inline, no dependency on shadcn Dialog to keep size lean)
// ---------------------------------------------------------------------------

interface ConfirmProps {
  symbol: string;
  action: "BUY" | "SELL";
  lots: number;
  quantity: number;
  onConfirm: () => void;
  onCancel: () => void;
}

function ConfirmOverlay({ symbol, action, lots, quantity, onConfirm, onCancel }: ConfirmProps) {
  return (
    <div
      className="absolute inset-0 bg-surface-base/90 backdrop-blur-sm flex flex-col items-center justify-center gap-3 z-10 rounded"
      role="dialog"
      aria-modal="true"
      aria-label="Confirm large order"
    >
      <div className="text-sm font-semibold text-text-primary">Confirm Order</div>
      <div className="text-xs text-text-secondary text-center px-4">
        {action} <span className="font-semibold text-text-primary">{lots} lots</span>{" "}
        (<span className="font-semibold text-text-primary">{quantity} qty</span>) of{" "}
        <span className="font-semibold text-text-primary">{symbol}</span>?
        <br />
        <span className="text-warning">Large order ({LARGE_ORDER_THRESHOLD}+ lots)</span>
      </div>
      <div className="flex gap-2">
        <Button
          variant="outline"
          size="sm"
          onClick={onCancel}
          className="px-3 py-1.5 text-xs border-border-default text-text-secondary hover:bg-surface-hover"
        >
          Cancel
        </Button>
        <Button
          size="sm"
          onClick={onConfirm}
          className={`px-3 py-1.5 text-xs font-semibold text-white transition-colors ${
            action === "BUY" ? "bg-profit hover:bg-profit/80" : "bg-loss hover:bg-loss/80"
          }`}
        >
          Confirm {action}
        </Button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main widget
// ---------------------------------------------------------------------------

/** Prefill params carried by a Dockview panel launching quicktrade. */
interface QuickTradePrefill {
  symbol?: string;
  exchange?: string;
}

function QuickTradeWidget(props: WidgetProps) {
  const mode = useModeStore((s) => s.mode);
  const track = useTrackBehavior();

  // Dockview delivers launcher-provided values under props.params — reading
  // top-level props silently dropped every prefill (the old hardcoded-NIFTY
  // bug). When no params are given, follow the workspace's selected
  // instrument (e.g. the active Watchlist row) so the ticket targets what the
  // trader is actually looking at. With neither, fail closed: render an
  // explicit "select an instrument" state — never silently default to
  // NIFTY/NSE and let a click place an order the trader did not target.
  const prefill = (props.params ?? {}) as QuickTradePrefill;
  const selectedInstrument = useAtomValue(selectedSymbolAtom);
  const symbol = prefill.symbol ?? selectedInstrument?.symbol ?? "";
  const exchange =
    prefill.exchange ?? (prefill.symbol ? "NSE" : selectedInstrument?.exchange ?? "");
  const hasInstrument = symbol !== "" && exchange !== "";

  const [lots, setLots] = useState<LotPreset>(1);
  const [product, setProduct] = useState<ProductType>("MIS");
  const [orderType, setOrderType] = useState<OrderType>("MARKET");
  const [limitPrice, setLimitPrice] = useState<string>("");
  const [status, setStatus] = useState<Status>(null);
  const [isPending, setIsPending] = useState(false);
  const [pendingAction, setPendingAction] = useState<"BUY" | "SELL" | null>(null);
  const [showConfirm, setShowConfirm] = useState(false);

  // Real lot size for the instrument — null until confirmed by the backend.
  const [lotSize, setLotSize] = useState<number | null>(null);
  useEffect(() => {
    if (!symbol || !exchange) return;
    let cancelled = false;
    setLotSize(null);
    getSymbol(symbol, exchange)
      .then((info) => {
        if (cancelled) return;
        // Equities report 0/1 — normalise to 1 so quantity = lots.
        setLotSize(info.lotsize > 0 ? info.lotsize : 1);
      })
      .catch(() => {
        // Leave null — derivative orders stay blocked (fail closed).
      });
    return () => {
      cancelled = true;
    };
  }, [symbol, exchange]);

  const isDerivative = DERIVATIVE_EXCHANGES.has(exchange);

  /**
   * Resolve the real order quantity (lots × lot size), or null when the lot
   * size is not yet confirmed for a derivatives contract — in which case no
   * order may be sent.
   */
  const resolveQuantity = useCallback((): number | null => {
    if (isDerivative && (lotSize == null || lotSize <= 0)) return null;
    return lots * (lotSize != null && lotSize > 0 ? lotSize : 1);
  }, [isDerivative, lotSize, lots]);

  const executeOrder = useCallback(
    async (action: "BUY" | "SELL") => {
      const quantity = resolveQuantity();
      if (quantity == null) {
        setStatus({
          type: "error",
          message: `Lot size for ${symbol} is unverified — order not sent`,
        });
        return;
      }
      setIsPending(true);
      setStatus(null);
      try {
        const price = orderType === "LIMIT" ? parseFloat(limitPrice) || 0 : 0;
        await placeOrder({
          symbol,
          exchange,
          action,
          quantity,
          price,
          triggerPrice: 0,
          product,
          orderType: orderType,
          strategy: "quicktrade",
        });
        setStatus({
          type: "success",
          message: `${action} order placed · ${lots} lot(s) = ${quantity} qty`,
        });
        track("trade", `quicktrade_${action.toLowerCase()}`);
        setTimeout(() => setStatus(null), 4000);
      } catch (err) {
        const msg = err instanceof Error ? err.message : "Order failed";
        setStatus({ type: "error", message: msg });
      } finally {
        setIsPending(false);
      }
    },
    [symbol, exchange, lots, product, orderType, limitPrice, track, resolveQuantity],
  );

  const handleAction = useCallback(
    (action: "BUY" | "SELL") => {
      // Belt-and-braces — the buttons are unreachable without an instrument,
      // but no order may ever leave this widget with an empty symbol.
      if (!hasInstrument) {
        setStatus({ type: "error", message: "Select an instrument first — order not sent" });
        return;
      }
      if (mode === "explore") {
        setStatus({ type: "error", message: "Connect a broker to place orders" });
        return;
      }
      if (resolveQuantity() == null) {
        setStatus({
          type: "error",
          message: `Lot size for ${symbol} is unverified — order not sent`,
        });
        return;
      }
      if (lots >= LARGE_ORDER_THRESHOLD) {
        setPendingAction(action);
        setShowConfirm(true);
        return;
      }
      void executeOrder(action);
    },
    [hasInstrument, lots, mode, executeOrder, resolveQuantity, symbol],
  );

  const handleConfirm = useCallback(() => {
    setShowConfirm(false);
    if (pendingAction) void executeOrder(pendingAction);
    setPendingAction(null);
  }, [pendingAction, executeOrder]);

  const handleCancel = useCallback(() => {
    setShowConfirm(false);
    setPendingAction(null);
  }, []);

  const displayQuantity = resolveQuantity();

  // Fail-closed empty state — no panel params and no workspace selection means
  // there is nothing safe to trade. Rendered after all hooks (hook-order rule).
  if (!hasInstrument) {
    return (
      <div className="relative h-full flex flex-col bg-surface-base overflow-hidden">
        <div className="flex-none flex items-center gap-2 px-2 py-1.5 bg-surface-card border-b border-border-default">
          <Zap size={13} className="text-accent shrink-0" aria-hidden="true" />
          <span className="text-xs font-semibold text-text-primary">Quick Trade</span>
        </div>
        <div
          role="status"
          className="flex-1 flex flex-col items-center justify-center gap-2 p-4 text-center"
        >
          <MousePointerClick size={20} className="text-text-muted" aria-hidden="true" />
          <p className="text-xs font-medium text-text-primary">Select an instrument</p>
          <p className="text-xxs text-text-muted max-w-52">
            Pick a scrip in the Watchlist, or open Quick Trade from a chart, to enable
            one-click orders. No default instrument is assumed.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="relative h-full flex flex-col bg-surface-base overflow-hidden">

      {/* Confirm overlay */}
      {showConfirm && pendingAction && displayQuantity != null && (
        <ConfirmOverlay
          symbol={symbol}
          action={pendingAction}
          lots={lots}
          quantity={displayQuantity}
          onConfirm={handleConfirm}
          onCancel={handleCancel}
        />
      )}

      {/* Header */}
      <div className="flex-none flex items-center gap-2 px-2 py-1.5 bg-surface-card border-b border-border-default">
        <Zap size={13} className="text-accent shrink-0" aria-hidden="true" />
        <span className="text-xs font-semibold text-text-primary">Quick Trade</span>
        <div className="flex-1" />
        <span className="px-1.5 py-0.5 text-xs font-mono font-semibold text-text-primary">
          {symbol}
        </span>
        <span className="px-1.5 py-0.5 text-xxs border border-border-default rounded text-text-muted">
          {exchange}
        </span>
      </div>

      <div className="flex-1 flex flex-col gap-2.5 p-2 min-h-0 overflow-y-auto">

        {/* Lot presets */}
        <div className="space-y-1">
          <div className="text-xxs text-text-muted uppercase tracking-wide">Lots</div>
          <div className="flex gap-1" role="group" aria-label="Lot size presets">
            {LOT_PRESETS.map((preset) => (
              <button
                key={preset}
                onClick={() => setLots(preset)}
                aria-pressed={lots === preset}
                className={`flex-1 py-1.5 text-sm font-semibold rounded border transition-colors ${
                  lots === preset
                    ? "bg-accent/15 text-accent border-accent/40"
                    : "text-text-secondary border-border-default hover:bg-surface-hover hover:text-text-primary"
                }`}
              >
                {preset}
              </button>
            ))}
          </div>
          {/* Effective quantity — the trader must see the real order size */}
          {displayQuantity != null ? (
            <div className="text-xxs text-text-muted font-mono tabular-nums">
              Qty: {lots} × {lotSize ?? 1} = {displayQuantity}
            </div>
          ) : (
            <div className="text-xxs text-warning" role="note">
              Lot size unverified — orders blocked until it loads
            </div>
          )}
        </div>

        {/* Product type */}
        <PillGroup label="Product" options={PRODUCT_TYPES} value={product} onChange={setProduct} />

        {/* Order type */}
        <PillGroup label="Order Type" options={ORDER_TYPES} value={orderType} onChange={setOrderType} />

        {/* Limit price (conditional) */}
        {orderType === "LIMIT" && (
          <div className="space-y-1">
            <label htmlFor="qt-limit-price" className="text-xxs text-text-muted uppercase tracking-wide">
              Limit Price
            </label>
            <Input
              id="qt-limit-price"
              type="number"
              step="0.05"
              min="0"
              value={limitPrice}
              onChange={(e) => setLimitPrice(e.target.value)}
              placeholder="0.00"
              className="h-7 text-xs font-mono"
              aria-label="Limit price"
            />
          </div>
        )}

        {/* Status */}
        <StatusBanner status={status} />

        {/* BUY / SELL */}
        <div className="flex gap-2 mt-auto">
          <Button
            onClick={() => handleAction("BUY")}
            disabled={isPending}
            aria-label={`Buy ${lots} lots of ${symbol}`}
            className="flex-1 h-10 text-sm font-bold bg-profit hover:bg-profit/80 text-white border-0"
          >
            {isPending && pendingAction === "BUY" ? (
              <Loader2 size={14} className="animate-spin mr-1" aria-hidden="true" />
            ) : null}
            BUY
          </Button>
          <Button
            onClick={() => handleAction("SELL")}
            disabled={isPending}
            aria-label={`Sell ${lots} lots of ${symbol}`}
            className="flex-1 h-10 text-sm font-bold bg-loss hover:bg-loss/80 text-white border-0"
          >
            {isPending && pendingAction === "SELL" ? (
              <Loader2 size={14} className="animate-spin mr-1" aria-hidden="true" />
            ) : null}
            SELL
          </Button>
        </div>
      </div>
    </div>
  );
}

export default memo(QuickTradeWidget);
