/**
 * OrderPadWidget — standalone order entry pad for FlintTrade terminal.
 * Migrated to TSX — Phase 4 Batch 1.
 *
 * Features:
 *   - Debounced symbol search with autocomplete dropdown (searchSymbol API)
 *   - Exchange badge on selected symbol
 *   - Order type pills: MARKET | LIMIT | SL | SL-M
 *   - Transaction toggle: BUY (green) / SELL (red)
 *   - Product type pills: MIS | NRML | CNC
 *   - Quantity with +/- lot stepper
 *   - Price input (enabled only for LIMIT / SL)
 *   - Trigger Price input (enabled only for SL / SL-M)
 *   - Disclosed Qty optional input
 *   - Place Order button — color matches action, shows spinner while pending
 *   - Success / error toast after placement
 *   - Default: NIFTY, NSE, BUY, MIS, MARKET, qty 1
 *   - react-hook-form + zod validation
 *   - FDC3 channel follower — an unpinned pad prefills from (and follows)
 *     the instrument broadcast on its joined user channel; a pad opened
 *     with explicit symbol params (a CreateOrder intent) ignores channels
 */

import { useState, useEffect, useRef, useCallback, memo } from "react";
import { useForm, Controller, type SubmitHandler, type Resolver } from "react-hook-form";
import { useAtomValue } from "jotai";
import { useModeStore } from "@/stores/modeStore";
import { tickAtomFamily } from "@/atoms/marketAtoms";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import {
  Search,
  X,
  Plus,
  Minus,
  Loader2,
  CheckCircle2,
  AlertCircle,
  FileEdit,
  IndianRupee,
  Hash,
  Wallet,
  Target,
} from "lucide-react";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { searchSymbol, placeOrder, getSymbol } from "@/services/api";
import { emitNotification } from "@/components/NotificationCentre/useNotificationFeed";
import { useMargin } from "@/hooks/useMargin";
import { useBrokerCapabilities } from "@/hooks/useBrokerCapabilities";
import {
  checkLotMultiple,
  checkOrderEntryMode,
  checkPriceForOrderType,
  isDerivativeExchange,
  OPTIONS_EXCHANGES,
} from "@/lib/orderGuards";
import type { PlaceOrderParams } from "@/types/api";
import type { WidgetProps } from "@/types/widgets";
import { isMarketHours, tickKeyFor } from "@/lib/market";
import { channelFromParams } from "@/services/fdc3/channels";
import { useChannelInstrument } from "@/services/fdc3/hooks";

// ─── Constants ────────────────────────────────────────────────────────────────

const ORDER_TYPES = ["MARKET", "LIMIT", "SL", "SL-M"] as const;
const PRODUCT_TYPES = ["MIS", "NRML", "CNC"] as const;

type OrderTypeValue = (typeof ORDER_TYPES)[number];
type ActionValue = "BUY" | "SELL";

const PRICE_ENABLED = new Set<OrderTypeValue>(["LIMIT", "SL"]);
const TRIGGER_ENABLED = new Set<OrderTypeValue>(["SL", "SL-M"]);

const DEBOUNCE_MS = 300;

// Lot-size, price, mode and derivative-exchange rules live in
// @/lib/orderGuards so every order-entry surface refuses the same things for
// the same reasons. OPTIONS_EXCHANGES drives the premium prefill below.

// NOTE: A "strike offset" selector (ATM/ITMn/OTMn) previously lived here. It
// computed a strike from the OPTION CONTRACT'S OWN PREMIUM (mistaking it for
// the underlying spot) and wrote that strike-like number into the order's
// LIMIT/SL PRICE field — an economically absurd limit price. Until a genuine
// underlying-spot feed and option-symbol replacement (getOptionSymbol) are
// wired, the pad prefills the price field from the option's live premium
// instead, and no strike arithmetic touches the price field.

// ─── Zod schema ───────────────────────────────────────────────────────────────

const orderSchema = z.object({
  symbol: z.string().min(1, "Symbol required"),
  exchange: z.string().min(1),
  action: z.enum(["BUY", "SELL"]),
  orderType: z.enum(["MARKET", "LIMIT", "SL", "SL-M"]),
  product: z.enum(["MIS", "NRML", "CNC"]),
  qty: z.coerce.number().int().min(1, "Quantity must be at least 1"),
  price: z.number().min(0).optional(),
  trigPrice: z.number().min(0).optional(),
  discQty: z.number().int().min(0).optional(),
});

type OrderFormValues = z.infer<typeof orderSchema>;

// ─── Sub-components ───────────────────────────────────────────────────────────

interface PillGroupProps {
  value: string;
  options: readonly string[];
  onChange: (v: string) => void;
  className?: string;
  label?: string;
}

function PillGroup({ value, options, onChange, className = "", label }: PillGroupProps) {
  function handleKeyDown(e: React.KeyboardEvent<HTMLDivElement>) {
    const idx = options.indexOf(value);
    if (e.key === "ArrowRight" || e.key === "ArrowDown") {
      e.preventDefault();
      onChange(options[(idx + 1) % options.length]);
    } else if (e.key === "ArrowLeft" || e.key === "ArrowUp") {
      e.preventDefault();
      onChange(options[(idx - 1 + options.length) % options.length]);
    }
  }

  return (
    <div
      role="radiogroup"
      aria-label={label}
      onKeyDown={handleKeyDown}
      className={`flex border border-border-default rounded overflow-hidden ${className}`}
    >
      {options.map((opt) => (
        <button
          key={opt}
          type="button"
          role="radio"
          aria-checked={value === opt}
          tabIndex={value === opt ? 0 : -1}
          onClick={() => onChange(opt)}
          className={`flex-1 h-8 text-xs font-medium transition-colors ${
            value === opt
              ? "bg-accent text-white"
              : "bg-surface-hover text-text-secondary hover:text-text-primary hover:bg-surface-card"
          }`}
        >
          {opt}
        </button>
      ))}
    </div>
  );
}

interface StepInputProps {
  label: string;
  value: string | number;
  onChange: (v: string) => void;
  min?: number;
  step?: number;
  disabled?: boolean;
  placeholder?: string;
  id?: string;
  errorId?: string;
  invalid?: boolean;
}

function StepInput({
  label,
  value,
  onChange,
  min = 0,
  step = 1,
  disabled = false,
  placeholder = "",
  id,
  errorId,
  invalid = false,
}: StepInputProps) {
  function dec() {
    const n = parseFloat(String(value)) || 0;
    onChange(String(Math.max(min, n - step)));
  }
  function inc() {
    const n = parseFloat(String(value)) || 0;
    onChange(String(n + step));
  }

  return (
    <div className="flex flex-col gap-0.5">
      <label htmlFor={id} className="text-xxs text-text-muted uppercase tracking-wider">{label}</label>
      <div className="flex items-stretch h-8">
        <Button
          type="button"
          variant="outline"
          size="icon"
          onClick={dec}
          disabled={disabled}
          aria-label={`Decrease ${label}`}
          className="w-8 h-8 flex items-center justify-center bg-surface-hover border border-r-0 border-border-default rounded-l rounded-r-none text-text-muted hover:text-text-primary hover:bg-surface-card transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
        >
          <Minus size={10} />
        </Button>
        <Input
          id={id}
          type="number"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          disabled={disabled}
          min={min}
          step={step}
          placeholder={placeholder}
          aria-invalid={invalid || undefined}
          aria-describedby={errorId}
          className="flex-1 min-w-0 bg-surface-hover border-y border-x-0 border-border-default rounded-none px-2 text-xs font-mono tabular-nums text-text-primary text-center focus-visible:ring-0 focus-visible:border-accent disabled:opacity-40 disabled:cursor-not-allowed placeholder:text-text-muted h-8"
        />
        <Button
          type="button"
          variant="outline"
          size="icon"
          onClick={inc}
          disabled={disabled}
          aria-label={`Increase ${label}`}
          className="w-8 h-8 flex items-center justify-center bg-surface-hover border border-l-0 border-border-default rounded-r rounded-l-none text-text-muted hover:text-text-primary hover:bg-surface-card transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
        >
          <Plus size={10} />
        </Button>
      </div>
    </div>
  );
}

interface NumFieldProps {
  label: string;
  value: string | number;
  onChange: (v: string) => void;
  disabled?: boolean;
  placeholder?: string;
  id?: string;
  errorId?: string;
  invalid?: boolean;
}

function NumField({ label, value, onChange, disabled = false, placeholder = "", id, errorId, invalid = false }: NumFieldProps) {
  return (
    <div className="flex flex-col gap-0.5">
      <label htmlFor={id} className="text-xxs text-text-muted uppercase tracking-wider">{label}</label>
      <Input
        id={id}
        type="number"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        disabled={disabled}
        placeholder={placeholder}
        aria-invalid={invalid || undefined}
        aria-describedby={errorId}
        className="h-8 w-full bg-surface-hover border border-border-default rounded px-2 text-xs font-mono tabular-nums text-text-primary focus-visible:ring-0 focus-visible:border-accent disabled:opacity-30 disabled:cursor-not-allowed placeholder:text-text-muted"
      />
    </div>
  );
}

function ExchangeBadge({ exchange }: { exchange: string }) {
  return (
    <span className="px-1.5 py-0.5 text-xxs font-semibold rounded bg-accent/10 border border-accent/20 text-accent uppercase tracking-wider">
      {exchange}
    </span>
  );
}

interface ToastMsg {
  type: "success" | "error";
  text: string;
  retryable?: boolean;
}

interface ToastProps {
  msg: ToastMsg | null;
  onRetry?: () => void;
}

function Toast({ msg, onRetry }: ToastProps) {
  if (!msg) return null;
  const ok = msg.type === "success";
  // Transient errors (network, server 500) are retryable; auth/validation errors are not
  const showRetry = !ok && msg.retryable && !!onRetry;
  return (
    <div
      role="alert"
      aria-live="assertive"
      className={`flex items-center gap-2 px-3 py-2 text-xs border-t ${
        ok
          ? "bg-profit/10 border-profit/20 text-profit"
          : "bg-loss/10 border-loss/20 text-loss"
      }`}
    >
      {ok ? <CheckCircle2 size={13} aria-hidden="true" /> : <AlertCircle size={13} aria-hidden="true" />}
      <span className="flex-1 leading-tight">{msg.text}</span>
      {showRetry && (
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={onRetry}
          className="shrink-0 h-auto px-2 py-0.5 rounded border border-loss/30 text-loss hover:bg-loss/10 transition-colors text-xxs font-medium"
        >
          Retry
        </Button>
      )}
    </div>
  );
}

// ─── Search suggestion shape ───────────────────────────────────────────────────
interface SymbolSuggestion {
  symbol?: string;
  ticker?: string;
  tradingsymbol?: string;
  exchange?: string;
  exch_seg?: string;
  name?: string;
  company_name?: string;
}

// ─── Main widget ──────────────────────────────────────────────────────────────

/** Prefill params carried by a `flinttrade:addWidget` orderpad request (W2). */
interface OrderPadPrefill {
  symbol?: string;
  exchange?: string;
  action?: "BUY" | "SELL";
}

function OrderPadWidget(props: WidgetProps) {
  // Optional prefill from a launcher (e.g. a CreateOrder intent or a
  // watchlist row-hover Buy/Sell). Only seeds the initial form; the user
  // still reviews and submits, and submission stays on the existing gated
  // placeOrder path.
  const prefill = (props.params ?? {}) as OrderPadPrefill;

  // FDC3 channel membership (Phase 2). A pad opened with an explicit
  // `symbol` param is PINNED: it joins no channel and ignores broadcasts
  // entirely, exactly as it ignored the global selection before. Otherwise
  // the pad reads its joined channel (red when params carry no `channel`
  // key; `channel: "none"` joins nothing) and the channel's instrument
  // slots between the params prefill and the NIFTY default.
  const isPinned = prefill.symbol != null;
  const channel = isPinned ? null : channelFromParams(props.params);
  const channelInstrument = useChannelInstrument(channel);

  const initialSymbol = prefill.symbol ?? channelInstrument?.symbol ?? "NIFTY";
  const initialExchange = prefill.exchange ?? channelInstrument?.exchange ?? "NSE";
  const initialAction: "BUY" | "SELL" = prefill.action === "SELL" ? "SELL" : "BUY";

  // Symbol search state (outside react-hook-form — ephemeral UI state)
  const [query, setQuery] = useState(initialSymbol);
  const [suggestions, setSuggestions] = useState<SymbolSuggestion[]>([]);
  const [searchOpen, setSearchOpen] = useState(false);
  const [searching, setSearching] = useState(false);

  const [loading, setLoading] = useState(false);
  const [toast, setToast] = useState<ToastMsg | null>(null);

  // Qty vs Fund mode toggle — "qty" = manual quantity, "fund" = enter INR amount and auto-calculate lots
  type InputMode = "qty" | "fund";
  const [inputMode, setInputMode] = useState<InputMode>("qty");

  // "Calculate from capital" state — user types an INR amount, qty is auto-calculated
  const [capitalAmount, setCapitalAmount] = useState("");

  // Lot size for the current symbol (0 = no lot constraint, e.g. equities).
  // Populated automatically via getSymbol when the symbol or exchange changes.
  const [lotSize, setLotSize] = useState(0);
  // Whether the lot size was actually confirmed by a symbol lookup. Derivative
  // exchanges (NFO/BFO/MCX/CDS) refuse to submit while this is false.
  const [lotSizeKnown, setLotSizeKnown] = useState(false);

  const searchRef = useRef<HTMLDivElement>(null);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const toastTimerRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const lastParamsRef = useRef<PlaceOrderParams | null>(null);

  const { control, handleSubmit, watch, setValue, setError, clearErrors, formState: { errors } } = useForm<OrderFormValues>({
    // zod v4 + @hookform/resolvers v5 type mismatch with z.coerce — safe at runtime
    resolver: zodResolver(orderSchema) as unknown as Resolver<OrderFormValues>,
    defaultValues: {
      symbol: initialSymbol,
      exchange: initialExchange,
      action: initialAction,
      orderType: "MARKET",
      product: "MIS",
      qty: 1,
      price: undefined,
      trigPrice: undefined,
      discQty: undefined,
    },
  });

  const orderType = watch("orderType") as OrderTypeValue;
  const action = watch("action") as ActionValue;
  const symbol = watch("symbol");
  const exchange = watch("exchange");
  const qty = watch("qty");
  const product = watch("product");
  const price = watch("price");
  const trigPrice = watch("trigPrice");

  const priceEnabled = PRICE_ENABLED.has(orderType);
  const triggerEnabled = TRIGGER_ENABLED.has(orderType);
  const isBuy = action === "BUY";

  // Live LTP for the selected symbol — used by the capital-to-quantity calculator.
  // Key format: "{exchange}:{symbol}" — matches the WS bridge and REST fallback
  // atom keys, with bare index names normalised to their *_INDEX exchange
  // (without this the default NIFTY read "NSE:NIFTY", which nothing writes,
  // so the LTP sat at 0 and the capital→qty calculator stayed inert).
  const tickKey = tickKeyFor(symbol, exchange);
  const tick = useAtomValue(tickAtomFamily(tickKey));
  const ltp = tick?.ltp ?? 0;

  // Options-specific: the tick for an NFO/BFO contract IS the option premium.
  const isOptionsExchange = OPTIONS_EXCHANGES.has(exchange);

  // Follow the joined channel: a fresh broadcast retargets the pad exactly
  // like picking the instrument from the search dropdown. The effect keys on
  // the broadcast object's identity, so an instrument already sitting on the
  // channel never re-asserts itself over a later local pick — local pick
  // beats stale channel context — while every NEW broadcast wins. Pinned
  // pads read a null channel and never enter. The truthiness guards keep the
  // form safe should a malformed context ever reach the channel atom.
  useEffect(() => {
    if (isPinned || !channelInstrument) return;
    const { symbol: chSymbol, exchange: chExchange } = channelInstrument;
    if (!chSymbol || !chExchange) return;
    setValue("symbol", chSymbol);
    setValue("exchange", chExchange);
    setQuery(chSymbol);
  }, [isPinned, channelInstrument, setValue]);

  // Fetch instrument metadata when symbol or exchange changes and auto-fill lot size.
  // On match, qty is set to the instrument's lotsize so the first order is valid.
  // The lot constraint is reset BEFORE the lookup so a failed fetch never leaves
  // a stale lot size from the previous instrument — derivative submissions fail
  // closed on an unknown lot size.
  useEffect(() => {
    if (!symbol || !exchange) return;
    let cancelled = false;
    setLotSize(0);
    setLotSizeKnown(false);
    const result = getSymbol(symbol, exchange);
    if (!result || typeof result.then !== "function") return;
    result.then((info) => {
        if (cancelled) return;
        // Coerce defensively — some adapters send numerics as strings.
        const ls = Number(info.lotsize ?? 0);
        if (Number.isFinite(ls) && ls > 0) {
          setLotSize(ls);
          setLotSizeKnown(true);
          setValue("qty", ls, { shouldValidate: true });
        }
      })
      .catch(() => {
        // Symbol not found or API unavailable — lot size stays unknown, and
        // derivative-exchange submissions are blocked until a lookup succeeds.
      });
    return () => {
      cancelled = true;
    };
  }, [symbol, exchange, setValue]);

  // When the user types an INR capital amount, auto-calculate quantity.
  // If lotSize > 0 the quantity is rounded down to the nearest lot:
  //   lots = floor(amount / (ltp * lotSize)),  qty = lots * lotSize
  // Also clears the capital field when qty is edited manually.
  const handleCapitalChange = useCallback(
    (raw: string) => {
      setCapitalAmount(raw);
      const amount = parseFloat(raw);
      if (!isNaN(amount) && amount > 0 && ltp > 0) {
        let calculated: number;
        if (lotSize > 0) {
          const lots = Math.floor(amount / (ltp * lotSize));
          calculated = lots * lotSize;
        } else {
          calculated = Math.floor(amount / ltp);
        }
        if (calculated >= 1) {
          setValue("qty", calculated);
        }
      }
    },
    [ltp, lotSize, setValue],
  );

  const handleQtyChange = useCallback(
    (v: string, fieldOnChange: (n: number) => void) => {
      // Manual qty edit clears the capital field to avoid confusion
      setCapitalAmount("");
      fieldOnChange(Number(v));
    },
    [],
  );

  // Broker capabilities — used to hide product for crypto, show dynamic exchanges
  const { data: brokerCaps } = useBrokerCapabilities();
  const isCryptoBroker = brokerCaps?.broker_type === "crypto";

  // Live margin requirement — enabled only when symbol + qty are set
  const { data: marginData, isFetching: marginFetching } = useMargin(
    symbol,
    exchange,
    qty,
    product,
    action,
    !!symbol && qty > 0,
  );

  // Close dropdown on outside click
  useEffect(() => {
    function onOutside(e: MouseEvent) {
      if (searchRef.current && !searchRef.current.contains(e.target as Node)) {
        setSearchOpen(false);
      }
    }
    document.addEventListener("mousedown", onOutside);
    return () => document.removeEventListener("mousedown", onOutside);
  }, []);

  // Debounced symbol search
  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    const q = query.trim();
    if (!q || q === symbol) {
      setSuggestions([]);
      setSearchOpen(false);
      return;
    }

    debounceRef.current = setTimeout(async () => {
      setSearching(true);
      try {
        const result = await searchSymbol(q);
        const list = Array.isArray(result) ? result : [];
        setSuggestions(list.slice(0, 8) as SymbolSuggestion[]);
        setSearchOpen(list.length > 0);
      } catch {
        setSuggestions([]);
        setSearchOpen(false);
      } finally {
        setSearching(false);
      }
    }, DEBOUNCE_MS);

    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, [query, symbol]);

  // Clear price/trigger when order type changes to non-requiring types
  useEffect(() => {
    if (!priceEnabled) setValue("price", undefined);
    if (!triggerEnabled) setValue("trigPrice", undefined);
  }, [orderType, priceEnabled, triggerEnabled, setValue]);

  // For a LIMIT/SL options order, prefill the empty price field with the
  // contract's live premium (its own LTP) — never a strike value. Prefills at
  // most once per contract/order-type so a user-typed price is never clobbered.
  const premiumPrefillKeyRef = useRef("");
  useEffect(() => {
    if (!isOptionsExchange || !priceEnabled || ltp <= 0) return;
    const key = `${exchange}:${symbol}:${orderType}`;
    if (premiumPrefillKeyRef.current === key) return;
    if (price == null || price === 0) {
      setValue("price", ltp);
      premiumPrefillKeyRef.current = key;
    }
  }, [isOptionsExchange, priceEnabled, ltp, exchange, symbol, orderType, price, setValue]);

  const handleSelect = useCallback(
    (item: SymbolSuggestion) => {
      const sym = item.symbol ?? item.ticker ?? item.tradingsymbol ?? "";
      const exch = item.exchange ?? item.exch_seg ?? "NSE";
      setValue("symbol", sym);
      setValue("exchange", exch);
      setQuery(sym);
      setSuggestions([]);
      setSearchOpen(false);
    },
    [setValue],
  );

  const handleClearSearch = useCallback(() => {
    setQuery("");
    setSuggestions([]);
    setSearchOpen(false);
  }, []);

  const showToast = useCallback((type: "success" | "error", text: string, ms = 4000, retryable = false) => {
    clearTimeout(toastTimerRef.current);
    setToast({ type, text, retryable });
    toastTimerRef.current = setTimeout(() => setToast(null), ms);
  }, []);

  useEffect(() => {
    return () => clearTimeout(toastTimerRef.current);
  }, []);

  // Determine whether an error message warrants a retry button
  function isRetryableError(msg: string): boolean {
    return (
      msg.includes("Connection failed") ||
      msg.includes("server error") ||
      msg.includes("Rate limit")
    );
  }

  const submitOrder = useCallback(async (params: PlaceOrderParams) => {
    setLoading(true);
    try {
      const result = await placeOrder(params);
      const orderId = (result as { orderId?: string; order_id?: string; orderid?: string }).orderId ??
        (result as { order_id?: string }).order_id ??
        (result as { orderid?: string }).orderid ?? "";
      showToast("success", `Order placed${orderId ? ` · ID: ${orderId}` : ""}`, 3000);
      // Log to the central Notification Centre (complements the transient toast).
      emitNotification({
        category: "order",
        title: `Order placed: ${params.action} ${params.quantity} ${params.symbol}`,
        body: orderId ? `Order ID ${orderId}` : "Submitted to the broker.",
      });
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Order failed";
      const retryable = isRetryableError(msg);
      showToast("error", msg, 6000, retryable);
      emitNotification({
        category: "order",
        title: `Order failed: ${params.action} ${params.symbol}`,
        body: msg,
        // A retryable failure (timeout, transient connection) sends the operator
        // back to the trade terminal to re-place; a hard rejection does not.
        ...(retryable ? { action: { label: "Back to terminal", href: "/trade" } } : {}),
      });
    } finally {
      setLoading(false);
    }
  }, [showToast]);

  const appMode = useModeStore((s) => s.mode);
  const isPracticeOrExplore = appMode === "practice" || appMode === "explore";

  const onSubmit: SubmitHandler<OrderFormValues> = async (values) => {
    clearErrors("qty");

    // Explore mode has no broker behind it — every price on screen is demo
    // data. The backend refuses too (403 mode_blocked), but the operator is
    // told here rather than after a round trip.
    const modeRefusal = checkOrderEntryMode(appMode);
    if (modeRefusal) {
      showToast("error", modeRefusal, 6000);
      return;
    }

    // F&O lot-multiple validation. Quantity on a derivative exchange must be a
    // positive multiple of the instrument's lot size; when the lot size is
    // unknown (symbol lookup failed) the submission fails closed rather than
    // sending a quantity the broker may reject — or worse, partially accept.
    const lotRefusal = checkLotMultiple(
      values.exchange,
      values.qty,
      { lotSize, verified: lotSizeKnown },
      values.symbol,
    );
    if (lotRefusal) {
      const msg = isDerivativeExchange(values.exchange) && !lotSizeKnown
        ? `Lot size unknown for ${values.symbol} (${values.exchange}) — cannot validate the F&O quantity. Reselect the symbol and try again.`
        : lotRefusal;
      setError("qty", { type: "validate", message: msg });
      showToast("error", msg, 6000);
      return;
    }

    // A LIMIT/SL order must carry a real price and an SL/SL-M a real trigger.
    // Sending ₹0 is a guaranteed broker rejection, and a lenient bridge could
    // treat it as marketable — turning a price-protected order into an
    // unprotected market order.
    const priceRefusal = checkPriceForOrderType(
      values.orderType,
      priceEnabled ? values.price : 1,
      triggerEnabled ? values.trigPrice : 1,
    );
    if (priceRefusal) {
      setError(priceEnabled && (values.price ?? 0) <= 0 ? "price" : "trigPrice", {
        type: "validate",
        message: priceRefusal,
      });
      showToast("error", priceRefusal, 6000);
      return;
    }

    // For a market-type order (MARKET / SL-M) the user never sets a price. In
    // Practice mode the paper engine needs a real fill price — a zero fabricates
    // a fill at 0.0 (now rejected by the sandbox), so feed the live LTP. Live
    // orders keep sending price 0 for market types (the broker fills at market),
    // so this fallback never alters the live-order payload.
    const isMarketType = values.orderType === "MARKET" || values.orderType === "SL-M";
    const practiceMarketFill = !priceEnabled && isMarketType && ltp > 0 && appMode === "practice";

    const params: PlaceOrderParams = {
      symbol: values.symbol,
      exchange: values.exchange,
      action: values.action,
      product: values.product as "MIS" | "CNC" | "NRML",
      orderType: values.orderType as "MARKET" | "LIMIT" | "SL" | "SL-M",
      quantity: values.qty,
      price: priceEnabled ? (values.price ?? 0) : practiceMarketFill ? ltp : 0,
      triggerPrice: triggerEnabled ? (values.trigPrice ?? 0) : 0,
      // The pad has always offered a disclosed-quantity input, but the value
      // was dropped before dispatch — operator intent silently discarded. The
      // backend has accepted `disclosed_quantity` all along.
      ...(values.discQty != null && values.discQty > 0
        ? { disclosedQuantity: values.discQty }
        : {}),
      strategy: "FlintOrderPad",
    };
    lastParamsRef.current = params;
    await submitOrder(params);
  };

  const handleRetry = useCallback(() => {
    if (lastParamsRef.current) {
      setToast(null);
      void submitOrder(lastParamsRef.current);
    }
  }, [submitOrder]);

  const btnBase =
    "flex items-center justify-center gap-2 w-full h-9 rounded font-semibold text-sm transition-colors disabled:opacity-60 disabled:cursor-not-allowed";
  const btnColor = isBuy
    ? "bg-profit hover:bg-profit/85 active:bg-profit/70 text-white"
    : "bg-loss hover:bg-loss/85 active:bg-loss/70 text-white";

  return (
    <div className="h-full flex flex-col bg-surface-base text-text-primary overflow-hidden" data-tour-target="order-pad">
      {/* Header */}
      <div className="flex-none bg-surface-card border-b border-border-default px-3 py-2 flex items-center gap-2">
        <FileEdit size={13} className="text-accent shrink-0" aria-hidden="true" />
        <span className="font-heading font-semibold text-sm text-text-primary uppercase tracking-wider">
          Order Pad
        </span>
        {isMarketHours() && (
          <span className="ml-auto text-xxs px-1.5 py-0.5 rounded bg-profit/10 border border-profit/20 text-profit font-medium">
            MARKET OPEN
          </span>
        )}
      </div>

      {/* Form body */}
      {/* noValidate: validation is owned by zod + the custom F&O lot check in
          onSubmit. Native constraint validation must stay off — the number
          input's step base is its min, so with min=1 and step=lotSize the
          browser flags exact lot multiples (e.g. 150 with lot 75) as a
          stepMismatch and silently blocks submission before handleSubmit runs. */}
      <form
        noValidate
        onSubmit={(e) => void handleSubmit(onSubmit)(e)}
        className="flex-1 flex flex-col gap-3 px-3 py-3 overflow-y-auto"
      >
        {/* Symbol search */}
        <div className="flex flex-col gap-0.5" ref={searchRef}>
          <label htmlFor="orderpad-symbol" className="text-xxs text-text-muted uppercase tracking-wider">Symbol</label>
          <div className="relative">
            <div className="flex items-center gap-1.5 h-9 bg-surface-hover border border-border-default rounded px-2 focus-within:border-accent transition-colors">
              <Search size={12} className="text-text-muted shrink-0" aria-hidden="true" />
              <input
                id="orderpad-symbol"
                type="text"
                value={query}
                onChange={(e) => setQuery(e.target.value.toUpperCase())}
                onFocus={() => {
                  if (query !== symbol && suggestions.length > 0) setSearchOpen(true);
                }}
                placeholder="Search symbol…"
                className="flex-1 bg-transparent text-xs font-mono text-text-primary focus:outline-none placeholder:text-text-muted"
                autoComplete="off"
                spellCheck={false}
                aria-invalid={!!errors.symbol || undefined}
                aria-describedby={errors.symbol ? "orderpad-symbol-error" : undefined}
              />
              {searching && (
                <Loader2 size={11} className="text-text-muted animate-spin shrink-0" aria-hidden="true" />
              )}
              {query && !searching && (
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  onClick={handleClearSearch}
                  className="h-auto w-auto p-0 text-text-muted hover:text-text-primary transition-colors"
                  aria-label="Clear search"
                >
                  <X size={11} />
                </Button>
              )}
              <ExchangeBadge exchange={exchange} />
            </div>

            {/* Autocomplete dropdown */}
            {searchOpen && suggestions.length > 0 && (
              <div className="absolute top-full left-0 right-0 mt-0.5 z-50 bg-surface-card border border-border-default rounded shadow-xl overflow-hidden">
                {suggestions.map((item, idx) => {
                  const sym = item.symbol ?? item.ticker ?? item.tradingsymbol ?? "";
                  const exch = item.exchange ?? item.exch_seg ?? "";
                  const name = item.name ?? item.company_name ?? "";
                  return (
                    <button
                      key={`${sym}-${idx}`}
                      type="button"
                      onClick={() => handleSelect(item)}
                      className="w-full flex items-center gap-2 px-3 py-2 text-left hover:bg-surface-hover transition-colors"
                    >
                      <span className="font-mono text-xs text-text-primary font-medium">{sym}</span>
                      {exch && <ExchangeBadge exchange={exch} />}
                      {name && (
                        <span className="text-xs text-text-muted truncate">{name}</span>
                      )}
                    </button>
                  );
                })}
              </div>
            )}
          </div>
          {errors.symbol && (
            <span id="orderpad-symbol-error" role="alert" className="text-xs text-loss mt-0.5">
              {errors.symbol.message}
            </span>
          )}
        </div>

        {/* BUY / SELL toggle */}
        <Controller
          control={control}
          name="action"
          render={({ field }) => {
            const actions = ["BUY", "SELL"] as const;
            function handleActionKeyDown(e: React.KeyboardEvent<HTMLDivElement>) {
              const idx = actions.indexOf(field.value as "BUY" | "SELL");
              if (e.key === "ArrowRight" || e.key === "ArrowDown") {
                e.preventDefault();
                field.onChange(actions[(idx + 1) % actions.length]);
              } else if (e.key === "ArrowLeft" || e.key === "ArrowUp") {
                e.preventDefault();
                field.onChange(actions[(idx - 1 + actions.length) % actions.length]);
              }
            }
            return (
              <div
                role="radiogroup"
                aria-label="Transaction type"
                onKeyDown={handleActionKeyDown}
                className="flex gap-2"
              >
                <button
                  type="button"
                  role="radio"
                  aria-checked={field.value === "BUY"}
                  tabIndex={field.value === "BUY" ? 0 : -1}
                  onClick={() => field.onChange("BUY")}
                  className={`flex-1 h-9 rounded font-semibold text-sm transition-colors border ${
                    field.value === "BUY"
                      ? "bg-bullish-bg border-bullish-border text-profit"
                      : "bg-surface-hover border-border-default text-text-secondary hover:text-text-primary"
                  }`}
                >
                  BUY
                </button>
                <button
                  type="button"
                  role="radio"
                  aria-checked={field.value === "SELL"}
                  tabIndex={field.value === "SELL" ? 0 : -1}
                  onClick={() => field.onChange("SELL")}
                  className={`flex-1 h-9 rounded font-semibold text-sm transition-colors border ${
                    field.value === "SELL"
                      ? "bg-bearish-bg border-bearish-border text-loss"
                      : "bg-surface-hover border-border-default text-text-secondary hover:text-text-primary"
                  }`}
                >
                  SELL
                </button>
              </div>
            );
          }}
        />

        {/* Order type */}
        <div className="flex flex-col gap-0.5">
          <label className="text-xxs text-text-muted uppercase tracking-wider">Order Type</label>
          <Controller
            control={control}
            name="orderType"
            render={({ field }) => (
              <PillGroup
                value={field.value}
                options={ORDER_TYPES}
                onChange={field.onChange}
              />
            )}
          />
        </div>

        {/* Options premium hint — shown for options exchanges (NFO/BFO) */}
        {isOptionsExchange && (
          <div className="flex flex-col gap-0.5">
            <span className="text-xxs text-text-muted uppercase tracking-wider flex items-center gap-1">
              <Target size={9} aria-hidden="true" />
              Option Premium
            </span>
            <p className="text-xxs text-text-muted">
              {ltp > 0 ? (
                <>
                  Live premium ₹{ltp.toLocaleString("en-IN", { maximumFractionDigits: 2 })} — prefills
                  the LIMIT/SL price field.
                </>
              ) : (
                "Live premium unavailable — enter the limit price manually."
              )}
            </p>
          </div>
        )}

        {/* Product type — hidden for crypto brokers (no product concept) */}
        {!isCryptoBroker && (
          <div className="flex flex-col gap-0.5">
            <label className="text-xxs text-text-muted uppercase tracking-wider">Product</label>
            <Controller
              control={control}
              name="product"
              render={({ field }) => (
                <PillGroup
                  value={field.value}
                  options={PRODUCT_TYPES}
                  onChange={field.onChange}
                />
              )}
            />
          </div>
        )}

        {/* Input mode toggle: Qty vs Fund */}
        <div className="flex items-center gap-2">
          <span className="text-xxs text-text-muted uppercase tracking-wider">Input</span>
          <div className="flex border border-border-default rounded overflow-hidden">
            <button
              type="button"
              onClick={() => setInputMode("qty")}
              className={`flex items-center gap-1 px-2.5 h-7 text-xs font-medium transition-colors ${
                inputMode === "qty"
                  ? "bg-accent text-white"
                  : "bg-surface-hover text-text-secondary hover:text-text-primary hover:bg-surface-card"
              }`}
              aria-pressed={inputMode === "qty"}
            >
              <Hash size={10} aria-hidden="true" />
              Qty
            </button>
            <button
              type="button"
              onClick={() => setInputMode("fund")}
              className={`flex items-center gap-1 px-2.5 h-7 text-xs font-medium transition-colors ${
                inputMode === "fund"
                  ? "bg-accent text-white"
                  : "bg-surface-hover text-text-secondary hover:text-text-primary hover:bg-surface-card"
              }`}
              aria-pressed={inputMode === "fund"}
            >
              <Wallet size={10} aria-hidden="true" />
              Fund
            </button>
          </div>
          {lotSize > 0 && (
            <span className="ml-auto text-xxs text-text-muted font-mono tabular-nums">
              Lot: {lotSize}
            </span>
          )}
        </div>

        {/* Qty mode: manual quantity + price row */}
        {inputMode === "qty" && (
          <div className="grid grid-cols-2 gap-3">
            <Controller
              control={control}
              name="qty"
              render={({ field }) => (
                <>
                  <StepInput
                    id="orderpad-qty"
                    label="Quantity"
                    value={field.value}
                    onChange={(v) => handleQtyChange(v, field.onChange)}
                    // One lot is the floor when the lot size is known, keeping the
                    // stepper (and the native spinner's step base) lot-aligned.
                    min={lotSize > 0 ? lotSize : 1}
                    step={lotSize > 0 ? lotSize : 1}
                    invalid={!!errors.qty}
                    errorId={errors.qty ? "orderpad-qty-error" : undefined}
                  />
                  {errors.qty && (
                    <span id="orderpad-qty-error" role="alert" className="text-xs text-loss col-span-2 -mt-2">
                      {errors.qty.message}
                    </span>
                  )}
                </>
              )}
            />
            <Controller
              control={control}
              name="price"
              render={({ field }) => (
                <NumField
                  id="orderpad-price"
                  label="Price"
                  value={field.value ?? ""}
                  onChange={(v) => field.onChange(v === "" ? undefined : Number(v))}
                  disabled={!priceEnabled}
                  placeholder={priceEnabled ? "0.00" : "N/A"}
                />
              )}
            />
          </div>
        )}

        {/* Fund mode: enter rupee amount, auto-calculate lots */}
        {inputMode === "fund" && (
          <div className="flex flex-col gap-2">
            <div className="flex flex-col gap-0.5">
              <label
                htmlFor="orderpad-capital"
                className="text-xxs text-text-muted uppercase tracking-wider flex items-center gap-1"
              >
                <IndianRupee size={9} aria-hidden="true" />
                Fund Amount
              </label>
              <div className="relative flex items-center">
                <span className="absolute left-2 text-xs text-text-muted font-mono pointer-events-none select-none">
                  ₹
                </span>
                <Input
                  id="orderpad-capital"
                  type="number"
                  min={0}
                  step={1000}
                  value={capitalAmount}
                  onChange={(e) => handleCapitalChange(e.target.value)}
                  placeholder="e.g. 50000"
                  className="pl-5 h-8 w-full bg-surface-hover border border-border-default rounded px-2 text-xs font-mono tabular-nums text-text-primary focus-visible:ring-0 focus-visible:border-accent placeholder:text-text-muted"
                />
              </div>
            </div>

            {/* Calculated quantity & approximate cost */}
            {capitalAmount !== "" && ltp > 0 && (() => {
              const amount = parseFloat(capitalAmount);
              let calculatedQty: number;
              let lots: number;
              if (lotSize > 0) {
                lots = Math.floor(amount / (ltp * lotSize));
                calculatedQty = lots * lotSize;
              } else {
                calculatedQty = Math.floor(amount / ltp);
                lots = calculatedQty;
              }
              const approxCost = calculatedQty * ltp;
              return (
                <div className="rounded border border-border-subtle bg-surface-card px-3 py-2 space-y-0.5">
                  <div className="flex justify-between text-xs">
                    <span className="text-text-muted">LTP</span>
                    <span className="font-mono tabular-nums text-text-primary">
                      ₹{ltp.toLocaleString("en-IN", { maximumFractionDigits: 2 })}
                    </span>
                  </div>
                  {lotSize > 0 && (
                    <div className="flex justify-between text-xs">
                      <span className="text-text-muted">Lots</span>
                      <span className="font-mono tabular-nums text-text-primary font-semibold">
                        {lots >= 1 ? lots : <span className="text-loss">0 — amount too small</span>}
                      </span>
                    </div>
                  )}
                  <div className="flex justify-between text-xs">
                    <span className="text-text-muted">Quantity</span>
                    <span className="font-mono tabular-nums text-text-primary font-semibold">
                      {calculatedQty >= 1 ? calculatedQty : <span className="text-loss">0 — amount too small</span>}
                    </span>
                  </div>
                  {calculatedQty >= 1 && (
                    <div className="flex justify-between text-xs">
                      <span className="text-text-muted">Approx Cost</span>
                      <span className="font-mono tabular-nums text-text-primary">
                        ₹{approxCost.toLocaleString("en-IN", { maximumFractionDigits: 2 })}
                      </span>
                    </div>
                  )}
                </div>
              );
            })()}
            {capitalAmount !== "" && ltp === 0 && (
              <p className="text-xxs text-text-muted">
                LTP unavailable — quantity not auto-calculated
              </p>
            )}

            {/* Price input in fund mode too */}
            <Controller
              control={control}
              name="price"
              render={({ field }) => (
                <NumField
                  id="orderpad-price-fund"
                  label="Price"
                  value={field.value ?? ""}
                  onChange={(v) => field.onChange(v === "" ? undefined : Number(v))}
                  disabled={!priceEnabled}
                  placeholder={priceEnabled ? "0.00" : "N/A"}
                />
              )}
            />
          </div>
        )}

        {/* Trigger + Disclosed row */}
        <div className="grid grid-cols-2 gap-3">
          <Controller
            control={control}
            name="trigPrice"
            render={({ field }) => (
              <NumField
                id="orderpad-trig-price"
                label="Trigger Price"
                value={field.value ?? ""}
                onChange={(v) => field.onChange(v === "" ? undefined : Number(v))}
                disabled={!triggerEnabled}
                placeholder={triggerEnabled ? "0.00" : "N/A"}
              />
            )}
          />
          <Controller
            control={control}
            name="discQty"
            render={({ field }) => (
              <NumField
                id="orderpad-disc-qty"
                label="Disclosed Qty"
                value={field.value ?? ""}
                onChange={(v) => field.onChange(v === "" ? undefined : Number(v))}
                placeholder="Optional"
              />
            )}
          />
        </div>

        {/* Order summary preview */}
        <div className="rounded border border-border-subtle bg-surface-card px-3 py-2 space-y-1">
          <div className="flex justify-between text-xs">
            <span className="text-text-muted">Symbol</span>
            <span className="font-mono tabular-nums text-text-primary font-semibold">{symbol}</span>
          </div>
          <div className="flex justify-between text-xs">
            <span className="text-text-muted">Exchange</span>
            <span className="font-mono text-text-primary">{exchange}</span>
          </div>
          <div className="flex justify-between text-xs">
            <span className="text-text-muted">Action</span>
            <span className={`font-semibold ${isBuy ? "text-profit" : "text-loss"}`}>{action}</span>
          </div>
          <div className="flex justify-between text-xs">
            <span className="text-text-muted">Qty / Product</span>
            <span className="font-mono tabular-nums text-text-primary">
              {qty} · {product}
            </span>
          </div>
          <div className="flex justify-between text-xs">
            <span className="text-text-muted">Type</span>
            <span className="font-mono text-text-primary">{orderType}</span>
          </div>
          {priceEnabled && price != null && price > 0 && (
            <div className="flex justify-between text-xs">
              <span className="text-text-muted">Price</span>
              <span className="font-mono tabular-nums text-text-primary">{price}</span>
            </div>
          )}
          {triggerEnabled && trigPrice != null && trigPrice > 0 && (
            <div className="flex justify-between text-xs">
              <span className="text-text-muted">Trigger</span>
              <span className="font-mono tabular-nums text-text-primary">{trigPrice}</span>
            </div>
          )}
        </div>

        {/* Margin requirement */}
        {marginData != null && (
          <div className={`rounded border border-border-default bg-surface-card px-3 py-2 transition-opacity ${marginFetching ? "opacity-50" : "opacity-100"}`}>
            <div className="flex justify-between items-baseline">
              <span className="text-xxs text-text-muted uppercase tracking-wider">Margin Required</span>
              <span className="font-mono text-xs font-semibold text-text-primary tabular-nums">
                ₹{marginData.total_margin_required.toLocaleString("en-IN", { maximumFractionDigits: 2 })}
              </span>
            </div>
            <div className="flex justify-between text-xxs text-text-muted mt-0.5 font-mono tabular-nums">
              <span>
                SPAN ₹{marginData.span_margin.toLocaleString("en-IN", { maximumFractionDigits: 2 })}
              </span>
              <span>
                Exposure ₹{marginData.exposure_margin.toLocaleString("en-IN", { maximumFractionDigits: 2 })}
              </span>
            </div>
          </div>
        )}

        {/* Submit button */}
        <Button
          type="submit"
          disabled={loading || !symbol || !qty}
          className={`${btnBase} ${btnColor}`}
        >
          {loading ? <Loader2 size={15} className="animate-spin" /> : null}
          {loading ? "Placing…" : isPracticeOrExplore ? `Practice ${action === "BUY" ? "Buy" : "Sell"}` : `Place ${action} Order`}
        </Button>
      </form>

      {/* Toast */}
      <Toast msg={toast} onRetry={handleRetry} />
    </div>
  );
}

export default memo(OrderPadWidget);
