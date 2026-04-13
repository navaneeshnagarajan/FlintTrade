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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { searchSymbol, placeOrder } from "@/services/api";
import { useMargin } from "@/hooks/useMargin";
import { useBrokerCapabilities } from "@/hooks/useBrokerCapabilities";
import type { PlaceOrderParams } from "@/types/api";
import type { WidgetProps } from "@/types/widgets";
import { isMarketHours } from "@/lib/market";

// ─── Constants ────────────────────────────────────────────────────────────────

const ORDER_TYPES = ["MARKET", "LIMIT", "SL", "SL-M"] as const;
const PRODUCT_TYPES = ["MIS", "NRML", "CNC"] as const;

type OrderTypeValue = (typeof ORDER_TYPES)[number];
type ActionValue = "BUY" | "SELL";

const PRICE_ENABLED = new Set<OrderTypeValue>(["LIMIT", "SL"]);
const TRIGGER_ENABLED = new Set<OrderTypeValue>(["SL", "SL-M"]);

const DEBOUNCE_MS = 300;

/** Exchanges that have option strikes (NFO = NSE F&O, BFO = BSE F&O). */
const OPTIONS_EXCHANGES = new Set(["NFO", "BFO"]);

/** Strike offset values. ATM = 0, ITMn = negative offset, OTMn = positive offset. */
type StrikeOffset =
  | "ATM"
  | "ITM1" | "ITM2" | "ITM3" | "ITM4" | "ITM5"
  | "ITM6" | "ITM7" | "ITM8" | "ITM9" | "ITM10"
  | "OTM1" | "OTM2" | "OTM3" | "OTM4" | "OTM5"
  | "OTM6" | "OTM7" | "OTM8" | "OTM9" | "OTM10";

const STRIKE_OFFSET_OPTIONS: StrikeOffset[] = [
  "ITM10", "ITM9", "ITM8", "ITM7", "ITM6", "ITM5", "ITM4", "ITM3", "ITM2", "ITM1",
  "ATM",
  "OTM1", "OTM2", "OTM3", "OTM4", "OTM5", "OTM6", "OTM7", "OTM8", "OTM9", "OTM10",
];

/**
 * Common strike gaps per instrument.
 * Falls back to 50 for NIFTY/BANKNIFTY/FINNIFTY etc.
 * These are standard NSE F&O strike intervals.
 */
const STRIKE_GAP_MAP: Record<string, number> = {
  NIFTY: 50,
  BANKNIFTY: 100,
  FINNIFTY: 50,
  MIDCPNIFTY: 25,
  SENSEX: 100,
  BANKEX: 100,
};

function getStrikeGap(symbol: string): number {
  const base = symbol.replace(/\d+/g, "").toUpperCase();
  return STRIKE_GAP_MAP[base] ?? 50;
}

/**
 * Calculate target strike from spot price, offset label, and strike gap.
 * For a BUY call (CE): ITM = lower strike, OTM = higher strike.
 * For a BUY put (PE): ITM = higher strike, OTM = lower strike.
 * We detect CE/PE from the symbol suffix; default to CE behaviour.
 */
function calculateStrike(
  spotLtp: number,
  offset: StrikeOffset,
  strikeGap: number,
  symbol: string,
): number {
  if (spotLtp <= 0 || strikeGap <= 0) return 0;

  const isPut = symbol.toUpperCase().endsWith("PE");
  const atmStrike = Math.round(spotLtp / strikeGap) * strikeGap;

  if (offset === "ATM") return atmStrike;

  const match = /^(ITM|OTM)(\d+)$/.exec(offset);
  if (!match) return atmStrike;

  const direction = match[1] as "ITM" | "OTM";
  const steps = parseInt(match[2], 10);

  // CE: ITM = below ATM, OTM = above ATM
  // PE: ITM = above ATM, OTM = below ATM
  const sign = (direction === "ITM") === !isPut ? -1 : 1;
  return atmStrike + sign * steps * strikeGap;
}

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
}

function StepInput({
  label,
  value,
  onChange,
  min = 0,
  step = 1,
  disabled = false,
  placeholder = "",
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
      <label className="text-xxs text-text-muted uppercase tracking-wider">{label}</label>
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
          type="number"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          disabled={disabled}
          min={min}
          step={step}
          placeholder={placeholder}
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
}

function NumField({ label, value, onChange, disabled = false, placeholder = "" }: NumFieldProps) {
  return (
    <div className="flex flex-col gap-0.5">
      <label className="text-xxs text-text-muted uppercase tracking-wider">{label}</label>
      <Input
        type="number"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        disabled={disabled}
        placeholder={placeholder}
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

function OrderPadWidget(_props: WidgetProps) {
  // Symbol search state (outside react-hook-form — ephemeral UI state)
  const [query, setQuery] = useState("NIFTY");
  const [suggestions, setSuggestions] = useState<SymbolSuggestion[]>([]);
  const [searchOpen, setSearchOpen] = useState(false);
  const [searching, setSearching] = useState(false);

  const [loading, setLoading] = useState(false);
  const [toast, setToast] = useState<ToastMsg | null>(null);

  // Qty vs Fund mode toggle — "qty" = manual quantity, "fund" = enter INR amount and auto-calculate lots
  type InputMode = "qty" | "fund";
  const [inputMode, setInputMode] = useState<InputMode>("qty");

  // Strike offset for options orders (NFO / BFO exchange)
  const [strikeOffset, setStrikeOffset] = useState<StrikeOffset>("ATM");

  // "Calculate from capital" state — user types an INR amount, qty is auto-calculated
  const [capitalAmount, setCapitalAmount] = useState("");

  // Lot size for the current symbol (0 = no lot constraint, e.g. equities).
  // TODO: populate from instrument master / option chain metadata when symbol changes.
  const [lotSize, _setLotSize] = useState(0);
  void _setLotSize; // suppress unused warning — will be wired to symbol metadata

  const searchRef = useRef<HTMLDivElement>(null);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const toastTimerRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const lastParamsRef = useRef<PlaceOrderParams | null>(null);

  const { control, handleSubmit, watch, setValue } = useForm<OrderFormValues>({
    // zodResolver v5 + zod v4 inferred type mismatch (coerce vs number): cast required
    resolver: zodResolver(orderSchema) as unknown as Resolver<OrderFormValues>,
    defaultValues: {
      symbol: "NIFTY",
      exchange: "NSE",
      action: "BUY",
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
  // Key format: "{exchange}:{symbol}" — matches the WS bridge and REST fallback atom keys.
  const tickKey = `${exchange}:${symbol}`;
  const tick = useAtomValue(tickAtomFamily(tickKey));
  const ltp = tick?.ltp ?? 0;

  // Options-specific: show strike offset selector when exchange is NFO or BFO
  const isOptionsExchange = OPTIONS_EXCHANGES.has(exchange);
  const strikeGap = getStrikeGap(symbol);

  // Auto-fill price when strike offset changes and we have LTP + LIMIT order
  const calculatedStrike = isOptionsExchange && ltp > 0
    ? calculateStrike(ltp, strikeOffset, strikeGap, symbol)
    : 0;

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

  // When strike offset changes on a LIMIT/SL options order, auto-fill the price field
  useEffect(() => {
    if (isOptionsExchange && priceEnabled && calculatedStrike > 0) {
      setValue("price", calculatedStrike);
    }
  }, [strikeOffset, isOptionsExchange, priceEnabled, calculatedStrike, setValue]);

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
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Order failed";
      showToast("error", msg, 6000, isRetryableError(msg));
    } finally {
      setLoading(false);
    }
  }, [showToast]);

  const onSubmit: SubmitHandler<OrderFormValues> = async (values) => {
    const params: PlaceOrderParams = {
      symbol: values.symbol,
      exchange: values.exchange,
      action: values.action,
      product: values.product as "MIS" | "CNC" | "NRML",
      orderType: values.orderType as "MARKET" | "LIMIT" | "SL" | "SL-M",
      quantity: values.qty,
      price: priceEnabled ? (values.price ?? 0) : 0,
      triggerPrice: triggerEnabled ? (values.trigPrice ?? 0) : 0,
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

  const appMode = useModeStore((s) => s.mode);
  const isPracticeOrExplore = appMode === "practice" || appMode === "explore";

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
      <form
        onSubmit={(e) => void handleSubmit(onSubmit)(e)}
        className="flex-1 flex flex-col gap-3 px-3 py-3 overflow-y-auto"
      >
        {/* Symbol search */}
        <div className="flex flex-col gap-0.5" ref={searchRef}>
          <label className="text-xxs text-text-muted uppercase tracking-wider">Symbol</label>
          <div className="relative">
            <div className="flex items-center gap-1.5 h-9 bg-surface-hover border border-border-default rounded px-2 focus-within:border-accent transition-colors">
              <Search size={12} className="text-text-muted shrink-0" aria-hidden="true" />
              <input
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

        {/* Strike offset selector — only shown for options exchanges (NFO/BFO) */}
        {isOptionsExchange && (
          <div className="flex flex-col gap-0.5">
            <label className="text-xxs text-text-muted uppercase tracking-wider flex items-center gap-1">
              <Target size={9} aria-hidden="true" />
              Strike Offset
            </label>
            <div className="flex items-center gap-2">
              <Select
                value={strikeOffset}
                onValueChange={(v) => setStrikeOffset(v as StrikeOffset)}
              >
                <SelectTrigger className="h-8 text-xs px-2 border-border-default bg-surface-hover text-text-primary flex-1 focus:ring-0 focus-visible:ring-0 focus-visible:border-accent">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent className="bg-surface-card border-border-default text-xs max-h-60">
                  {STRIKE_OFFSET_OPTIONS.map((opt) => (
                    <SelectItem
                      key={opt}
                      value={opt}
                      className={`text-xs font-mono ${
                        opt === "ATM"
                          ? "text-accent font-semibold"
                          : opt.startsWith("ITM")
                          ? "text-profit"
                          : "text-loss"
                      }`}
                    >
                      {opt}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              {calculatedStrike > 0 && (
                <span className="text-xs font-mono tabular-nums text-text-secondary shrink-0">
                  → {calculatedStrike}
                </span>
              )}
            </div>
            {calculatedStrike > 0 && (
              <p className="text-xxs text-text-muted">
                Spot ≈ {ltp > 0 ? ltp.toLocaleString("en-IN", { maximumFractionDigits: 2 }) : "—"} · Gap {strikeGap} · Strike {calculatedStrike}
              </p>
            )}
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
                <StepInput
                  label="Quantity"
                  value={field.value}
                  onChange={(v) => handleQtyChange(v, field.onChange)}
                  min={1}
                  step={lotSize > 0 ? lotSize : 1}
                />
              )}
            />
            <Controller
              control={control}
              name="price"
              render={({ field }) => (
                <NumField
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
