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

import { useState, useEffect, useRef, useCallback } from "react";
import { useForm, Controller, type SubmitHandler, type Resolver } from "react-hook-form";
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
} from "lucide-react";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { searchSymbol, placeOrder } from "@/services/api";
import { useMargin } from "@/hooks/useMargin";
import type { PlaceOrderParams } from "@/types/api";
import type { WidgetProps } from "@/types/widgets";

// ─── Constants ────────────────────────────────────────────────────────────────

const ORDER_TYPES = ["MARKET", "LIMIT", "SL", "SL-M"] as const;
const PRODUCT_TYPES = ["MIS", "NRML", "CNC"] as const;

type OrderTypeValue = (typeof ORDER_TYPES)[number];
type ActionValue = "BUY" | "SELL";

const PRICE_ENABLED = new Set<OrderTypeValue>(["LIMIT", "SL"]);
const TRIGGER_ENABLED = new Set<OrderTypeValue>(["SL", "SL-M"]);

const DEBOUNCE_MS = 300;

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

// ─── Helpers ─────────────────────────────────────────────────────────────────

function isMarketHours(): boolean {
  const ist = new Date(new Date().toLocaleString("en-US", { timeZone: "Asia/Kolkata" }));
  const day = ist.getDay();
  if (day === 0 || day === 6) return false;
  const mins = ist.getHours() * 60 + ist.getMinutes();
  return mins >= 555 && mins <= 930;
}

// ─── Sub-components ───────────────────────────────────────────────────────────

interface PillGroupProps {
  value: string;
  options: readonly string[];
  onChange: (v: string) => void;
  className?: string;
}

function PillGroup({ value, options, onChange, className = "" }: PillGroupProps) {
  return (
    <div className={`flex border border-border-default rounded overflow-hidden ${className}`}>
      {options.map((opt) => (
        <button
          key={opt}
          type="button"
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
        <button
          type="button"
          onClick={dec}
          disabled={disabled}
          className="w-8 flex items-center justify-center bg-surface-hover border border-r-0 border-border-default rounded-l text-text-muted hover:text-text-primary hover:bg-surface-card transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
        >
          <Minus size={10} />
        </button>
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
        <button
          type="button"
          onClick={inc}
          disabled={disabled}
          className="w-8 flex items-center justify-center bg-surface-hover border border-l-0 border-border-default rounded-r text-text-muted hover:text-text-primary hover:bg-surface-card transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
        >
          <Plus size={10} />
        </button>
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
}

function Toast({ msg }: { msg: ToastMsg | null }) {
  if (!msg) return null;
  const ok = msg.type === "success";
  return (
    <div
      className={`flex items-center gap-2 px-3 py-2 text-xs border-t ${
        ok
          ? "bg-profit/10 border-profit/20 text-profit"
          : "bg-loss/10 border-loss/20 text-loss"
      }`}
    >
      {ok ? <CheckCircle2 size={13} /> : <AlertCircle size={13} />}
      <span className="flex-1 leading-tight">{msg.text}</span>
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

export default function OrderPadWidget(_props: WidgetProps) {
  // Symbol search state (outside react-hook-form — ephemeral UI state)
  const [query, setQuery] = useState("NIFTY");
  const [suggestions, setSuggestions] = useState<SymbolSuggestion[]>([]);
  const [searchOpen, setSearchOpen] = useState(false);
  const [searching, setSearching] = useState(false);

  const [loading, setLoading] = useState(false);
  const [toast, setToast] = useState<ToastMsg | null>(null);

  const searchRef = useRef<HTMLDivElement>(null);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

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

  const showToast = useCallback((type: "success" | "error", text: string, ms = 4000) => {
    setToast({ type, text });
    setTimeout(() => setToast(null), ms);
  }, []);

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

    setLoading(true);
    try {
      const result = await placeOrder(params);
      const orderId = (result as { orderId?: string; order_id?: string }).orderId ??
        (result as { order_id?: string }).order_id ?? "";
      showToast("success", `Order placed${orderId ? ` · ID: ${orderId}` : ""}`);
    } catch (err) {
      showToast("error", err instanceof Error ? err.message : "Order failed");
    } finally {
      setLoading(false);
    }
  };

  const btnBase =
    "flex items-center justify-center gap-2 w-full h-9 rounded font-semibold text-sm transition-colors disabled:opacity-60 disabled:cursor-not-allowed";
  const btnColor = isBuy
    ? "bg-profit hover:bg-profit/85 active:bg-profit/70 text-white"
    : "bg-loss hover:bg-loss/85 active:bg-loss/70 text-white";

  return (
    <div className="h-full flex flex-col bg-surface-base text-text-primary overflow-hidden">
      {/* Header */}
      <div className="flex-none bg-surface-card border-b border-border-default px-3 py-2 flex items-center gap-2">
        <FileEdit size={13} className="text-accent shrink-0" />
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
              <Search size={12} className="text-text-muted shrink-0" />
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
                <Loader2 size={11} className="text-text-muted animate-spin shrink-0" />
              )}
              {query && !searching && (
                <button
                  type="button"
                  onClick={handleClearSearch}
                  className="text-text-muted hover:text-text-primary transition-colors"
                >
                  <X size={11} />
                </button>
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
          render={({ field }) => (
            <div className="flex gap-2">
              <button
                type="button"
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
          )}
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

        {/* Product type */}
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

        {/* Qty + Price row */}
        <div className="grid grid-cols-2 gap-3">
          <Controller
            control={control}
            name="qty"
            render={({ field }) => (
              <StepInput
                label="Quantity"
                value={field.value}
                onChange={(v) => field.onChange(Number(v))}
                min={1}
                step={1}
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
          {loading ? "Placing…" : `Place ${action} Order`}
        </Button>
      </form>

      {/* Toast */}
      <Toast msg={toast} />
    </div>
  );
}
