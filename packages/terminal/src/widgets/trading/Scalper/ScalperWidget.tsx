// Migrated to TSX — Phase 4 Batch 1
// Direct API calls (placeOrder, cancelAllOrders, closePosition, getExpiry, getQuotes)
// are intentional here: Scalper requires interactive one-click orders, not cached REST data.
import { useState, useEffect, useRef, useCallback, useMemo, memo } from "react";
import {
  Zap,
  ZapOff,
  Plus,
  Minus,
  TrendingUp,
  TrendingDown,
  X,
  RefreshCw,
  AlertTriangle,
} from "lucide-react";
import Chart from "@/components/Chart";
import { Input } from "@/components/ui/input";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  placeOrder,
  cancelAllOrders,
  closePosition,
  getExpiry,
  getQuotes,
} from "@/services/api";
import useWebSocket from "@/hooks/useWebSocket";
import type { PlaceOrderParams, WsInstrument, WsTick } from "@/types/api";
import type { WidgetProps } from "@/types/widgets";

// ─── Local types ──────────────────────────────────────────────────────────────

/** WsTick extended with optional prev_close that some OpenAlgo responses carry */
interface TickData extends WsTick {
  prev_close?: number;
}

type TickMap = Record<string, TickData>;

type OrderAction = "BUY" | "SELL";
type ProductType = "MIS" | "NRML";
type OrderTypeValue = "MARKET" | "LIMIT";
type IntervalValue = "1m" | "3m" | "5m" | "15m";
type StatusType = "idle" | "success" | "error" | "pending";

interface PendingOrder {
  sym: string;
  exch: string;
  action: OrderAction;
}

interface StatusState {
  message: string;
  type: StatusType;
}

// ─── Constants ────────────────────────────────────────────────────────────────

interface IndexConfig {
  exchange: string;
  optExchange: string;
  lotSize: number;
  step: number;
}

const INDEX_CONFIG: Record<string, IndexConfig> = {
  NIFTY:      { exchange: "NSE_INDEX", optExchange: "NFO",  lotSize: 75,  step: 50  },
  BANKNIFTY:  { exchange: "NSE_INDEX", optExchange: "NFO",  lotSize: 30,  step: 100 },
  FINNIFTY:   { exchange: "NSE_INDEX", optExchange: "NFO",  lotSize: 40,  step: 50  },
  MIDCPNIFTY: { exchange: "NSE_INDEX", optExchange: "NFO",  lotSize: 50,  step: 25  },
  SENSEX:     { exchange: "BSE_INDEX", optExchange: "BFO",  lotSize: 10,  step: 100 },
  BANKEX:     { exchange: "BSE_INDEX", optExchange: "BFO",  lotSize: 15,  step: 100 },
};

const SYMBOLS = Object.keys(INDEX_CONFIG);
const DEFAULT_SYMBOL = "NIFTY";

// ─── Helpers ─────────────────────────────────────────────────────────────────

const fmt2 = (n: number | null | undefined): string =>
  n == null || isNaN(n) ? "—" : Number(n).toFixed(2);

const fmtInt = (n: number | null | undefined): string =>
  n == null || isNaN(n) ? "—" : Math.round(n).toLocaleString("en-IN");

function roundToStrike(price: number, step: number): number {
  return Math.round(price / step) * step;
}

function buildOptionSymbol(
  base: string,
  expiry: string,
  strike: number,
  type: "CE" | "PE",
): string | null {
  if (!expiry) return null;
  let exp = expiry;
  if (exp.includes("-")) {
    const d = new Date(exp);
    const day = String(d.getDate()).padStart(2, "0");
    const mon = d.toLocaleString("en-US", { month: "short" }).toUpperCase();
    const yr = String(d.getFullYear()).slice(2);
    exp = `${day}${mon}${yr}`;
  }
  return `${base}${exp}${strike}${type}`;
}

// ─── Sub-components ───────────────────────────────────────────────────────────

interface LtpBlockProps {
  label: string;
  symbol: string;
  exchange: string;
  ticks: TickMap;
  className?: string;
}

function LtpBlock({ label, symbol, exchange, ticks, className = "" }: LtpBlockProps) {
  const key = `${exchange}:${symbol}`;
  const tick = ticks[key];
  const ltp = tick?.ltp ?? tick?.close ?? null;
  const close = tick?.prev_close ?? tick?.close ?? null;
  const chg = ltp != null && close ? ltp - close : null;
  const pct = chg != null && close ? (chg / close) * 100 : null;
  const up = chg == null ? null : chg >= 0;

  return (
    <div className={`flex items-baseline gap-1.5 ${className}`}>
      <span className="text-xxs text-text-muted uppercase tracking-wider font-sans">{label}</span>
      <span className="font-mono text-sm font-bold text-text-primary">
        {ltp != null ? fmtInt(ltp) : "—"}
      </span>
      {chg != null && (
        <span className={`font-mono text-xs ${up ? "text-profit" : "text-loss"}`}>
          {up ? "+" : ""}{fmt2(chg)} ({up ? "+" : ""}{fmt2(pct)}%)
        </span>
      )}
    </div>
  );
}

interface StepperProps {
  label: string;
  value: string;
  onDec: () => void;
  onInc: () => void;
  sublabel?: string;
  large?: boolean;
  className?: string;
}

function Stepper({ label, value, onDec, onInc, sublabel, large = false, className = "" }: StepperProps) {
  const btnSize = large ? "w-8 h-8" : "w-6 h-8";
  const iconSize = large ? 12 : 10;
  const valueClass = large
    ? "font-mono text-sm font-bold text-text-primary bg-surface-card border-y border-border-default px-2 h-8 flex items-center min-w-14 justify-center"
    : "font-mono text-sm font-bold text-text-primary bg-surface-card border-y border-border-default px-2 h-8 flex items-center min-w-12 justify-center";

  return (
    <div className={`flex flex-col gap-0.5 ${className}`}>
      <span className="text-xxs text-text-muted uppercase tracking-wider font-sans">
        {label}
        {sublabel && <span className="text-text-disabled ml-1">{sublabel}</span>}
      </span>
      <div className="flex items-center">
        <button
          type="button"
          onClick={onDec}
          aria-label={`Decrease ${label}`}
          className={`${btnSize} flex items-center justify-center text-text-muted hover:text-text-primary bg-surface-hover border border-border-default rounded-l-md hover:bg-surface-card transition-colors`}
        >
          <Minus size={iconSize} />
        </button>
        <span className={valueClass}>
          {value}
        </span>
        <button
          type="button"
          onClick={onInc}
          aria-label={`Increase ${label}`}
          className={`${btnSize} flex items-center justify-center text-text-muted hover:text-text-primary bg-surface-hover border border-border-default rounded-r-md hover:bg-surface-card transition-colors`}
        >
          <Plus size={iconSize} />
        </button>
      </div>
    </div>
  );
}

interface NumberInputProps {
  label: string;
  value: string | number;
  onChange: (v: string) => void;
  min?: number;
  placeholder?: string;
  className?: string;
}

function NumberInput({
  label,
  value,
  onChange,
  min = 0,
  placeholder,
  className = "",
}: NumberInputProps) {
  return (
    <div className={`flex flex-col gap-0.5 ${className}`}>
      <span className="text-xxs text-text-muted uppercase tracking-wider font-sans">
        {label}
      </span>
      <Input
        type="number"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        min={min}
        placeholder={placeholder}
        className="w-16 h-8 text-sm font-mono"
      />
    </div>
  );
}

interface ToggleGroupProps {
  label?: string;
  value: string;
  options: readonly string[];
  onChange: (v: string) => void;
  className?: string;
}

function ToggleGroup({ label, value, options, onChange, className = "" }: ToggleGroupProps) {
  return (
    <div className={`flex flex-col gap-0.5 ${className}`}>
      {label && (
        <span className="text-xxs text-text-muted uppercase tracking-wider font-sans">{label}</span>
      )}
      <div role="radiogroup" aria-label={label} className="flex border border-border-default rounded-md overflow-hidden">
        {options.map((opt) => (
          <button
            key={opt}
            type="button"
            role="radio"
            aria-checked={value === opt}
            onClick={() => onChange(opt)}
            className={`px-2.5 h-8 text-xs font-semibold transition-colors ${
              value === opt
                ? "bg-accent/15 text-accent border-accent/40"
                : "bg-surface-hover text-text-secondary hover:text-text-primary"
            }`}
          >
            {opt}
          </button>
        ))}
      </div>
    </div>
  );
}

interface StatusPillProps {
  message: string;
  type?: StatusType;
}

function StatusPill({ message, type = "idle" }: StatusPillProps) {
  if (!message) return null;
  const colors: Record<StatusType, string> = {
    success: "text-profit bg-profit/10 border-profit/30",
    error:   "text-loss bg-loss/10 border-loss/30",
    pending: "text-warning bg-warning/10 border-warning/30",
    idle:    "text-text-muted bg-surface-hover border-border-default",
  };
  return (
    <span
      className={`inline-flex items-center gap-1 px-2 py-1 rounded-md border text-xs font-mono ${colors[type]}`}
    >
      {type === "pending" && <RefreshCw size={10} className="animate-spin" />}
      {type === "error" && <AlertTriangle size={10} />}
      {message}
    </span>
  );
}

// ─── Action button sub-component ─────────────────────────────────────────────

interface ActionButtonProps {
  onClick: () => void;
  disabled?: boolean;
  title: string;
  variant: "buy" | "sell" | "neutral" | "warning";
  icon: React.ReactNode;
  label: string;
  shortcut: string;
}

function ActionButton({ onClick, disabled = false, title, variant, icon, label, shortcut }: ActionButtonProps) {
  const variantClasses: Record<string, string> = {
    buy:     "bg-profit/10 text-profit border-profit/30 hover:bg-profit/20",
    sell:    "bg-loss/10 text-loss border-loss/30 hover:bg-loss/20",
    neutral: "bg-surface-card text-text-muted border-border-default hover:bg-surface-hover",
    warning: "bg-surface-card text-text-muted border-border-default hover:bg-surface-hover",
  };

  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      title={title}
      className={`flex-1 flex flex-col items-center justify-center gap-0.5 py-2 border text-sm font-semibold transition-colors disabled:opacity-30 disabled:cursor-not-allowed ${variantClasses[variant]}`}
    >
      <span className="flex items-center gap-1">
        {icon}
        {label}
      </span>
      <span className="text-xxs text-text-disabled font-sans font-normal">{shortcut}</span>
    </button>
  );
}

// ─── Main widget ──────────────────────────────────────────────────────────────

function ScalperWidget(_props: WidgetProps) {
  const [symbol, setSymbol] = useState(DEFAULT_SYMBOL);
  const [lots, setLots] = useState(1);
  const [product, setProduct] = useState<ProductType>("MIS");
  const [orderType, setOrderType] = useState<OrderTypeValue>("MARKET");
  const [sl, setSl] = useState("");
  const [target, setTarget] = useState("");
  const [oneClick, setOneClick] = useState(false);
  const [interval, setInterval_] = useState<IntervalValue>("5m");

  const [expiries, setExpiries] = useState<string[]>([]);
  const [expiriesError, setExpiriesError] = useState(false);
  const [expiry, setExpiry] = useState("");
  const [atmStrike, setAtmStrike] = useState<number | null>(null);
  const [ceOffset, setCeOffset] = useState(0);
  const [peOffset, setPeOffset] = useState(0);

  const [status, setStatus] = useState<StatusState>({ message: "", type: "idle" });
  const [pendingOrder, setPendingOrder] = useState<PendingOrder | null>(null);
  const [closeAllOpen, setCloseAllOpen] = useState(false);
  const [cancelAllOpen, setCancelAllOpen] = useState(false);

  const containerRef = useRef<HTMLDivElement>(null);
  const confirmBtnRef = useRef<HTMLButtonElement>(null);
  const [focused, setFocused] = useState(false);

  useEffect(() => {
    if (pendingOrder) {
      confirmBtnRef.current?.focus();
    }
  }, [pendingOrder]);

  const cfg = INDEX_CONFIG[symbol] ?? INDEX_CONFIG[DEFAULT_SYMBOL];
  const step = cfg.step;
  const lotSize = cfg.lotSize;
  const spotExch = cfg.exchange;
  const optExch = cfg.optExchange;

  const ceStrike = atmStrike != null ? atmStrike + ceOffset * step : null;
  const peStrike = atmStrike != null ? atmStrike + peOffset * step : null;

  const ceSymbol = ceStrike != null ? buildOptionSymbol(symbol, expiry, ceStrike, "CE") : null;
  const peSymbol = peStrike != null ? buildOptionSymbol(symbol, expiry, peStrike, "PE") : null;

  const instruments = useMemo<WsInstrument[]>(() => {
    const list: WsInstrument[] = [{ symbol, exchange: spotExch }];
    if (ceSymbol) list.push({ symbol: ceSymbol, exchange: optExch });
    if (peSymbol) list.push({ symbol: peSymbol, exchange: optExch });
    return list;
  }, [symbol, spotExch, ceSymbol, peSymbol, optExch]);

  const { ticks } = useWebSocket(instruments, "quote");

  const spotKey = `${spotExch}:${symbol}`;
  const spotTick = ticks[spotKey];
  const spotLtp = spotTick?.ltp ?? spotTick?.close ?? null;

  // Fetch expiries on symbol change
  const fetchExpiries = useCallback(
    async (signal?: { cancelled: boolean }) => {
      setExpiriesError(false);
      setExpiries([]);
      setExpiry("");
      try {
        const data = await getExpiry(symbol, optExch);
        if (signal?.cancelled) return;
        const list = Array.isArray(data) ? data : (data?.expiry ?? []);
        setExpiries(list);
        if (list.length > 0) setExpiry(list[0]);
      } catch {
        if (signal?.cancelled) return;
        setExpiriesError(true);
      }
    },
    [symbol, optExch],
  );

  useEffect(() => {
    const signal = { cancelled: false };
    setAtmStrike(null);
    void fetchExpiries(signal);
    return () => {
      signal.cancelled = true;
    };
  }, [fetchExpiries]);

  // Resolve ATM from spot tick (fast path)
  useEffect(() => {
    if (spotLtp != null) {
      setAtmStrike(roundToStrike(spotLtp, step));
    }
  }, [spotLtp, step]);

  // Fallback: fetch from API once if tick not yet available
  useEffect(() => {
    if (spotLtp != null || !symbol) return;
    let cancelled = false;

    async function fetchSpot() {
      try {
        const q = await getQuotes(symbol, spotExch);
        if (cancelled) return;
        const ltp = q?.ltp ?? q?.close ?? null;
        if (ltp) setAtmStrike(roundToStrike(ltp, step));
      } catch {
        // silently ignore
      }
    }

    void fetchSpot();
    return () => {
      cancelled = true;
    };
  }, [symbol, spotExch, spotLtp, step]);

  const showStatus = useCallback((message: string, type: StatusType = "success", ms = 3000) => {
    setStatus({ message, type });
    if (ms) setTimeout(() => setStatus({ message: "", type: "idle" }), ms);
  }, []);

  const executeOrder = useCallback(
    async (sym: string | null, exch: string, action: OrderAction) => {
      if (!sym) {
        showStatus("Strike not resolved", "error");
        return;
      }
      const qty = lots * lotSize;

      const params: PlaceOrderParams = {
        symbol: sym,
        exchange: exch,
        action,
        quantity: qty,
        orderType,
        product,
        price: 0,
        strategy: "FlintScalper",
      };

      showStatus(`${action} ${sym} × ${qty}…`, "pending", 0);
      try {
        await placeOrder(params);
        showStatus(`${action} ${sym} filled`, "success");
      } catch (err) {
        showStatus(err instanceof Error ? err.message : "Order failed", "error");
      }
    },
    [lots, lotSize, orderType, product, showStatus],
  );

  const handleOrder = useCallback(
    (sym: string | null, exch: string, action: OrderAction) => {
      if (oneClick) {
        void executeOrder(sym, exch, action);
      } else {
        if (sym) setPendingOrder({ sym, exch, action });
      }
    },
    [oneClick, executeOrder],
  );

  const confirmOrder = useCallback(() => {
    if (pendingOrder) {
      void executeOrder(pendingOrder.sym, pendingOrder.exch, pendingOrder.action);
      setPendingOrder(null);
    }
  }, [pendingOrder, executeOrder]);

  const handleCloseAll = useCallback(() => {
    setCloseAllOpen(true);
  }, []);

  const confirmCloseAll = useCallback(async () => {
    setCloseAllOpen(false);
    showStatus("Closing all…", "pending", 0);
    try {
      await closePosition("FlintScalper");
      showStatus("All positions closed", "success");
    } catch (err) {
      showStatus(err instanceof Error ? err.message : "Close failed", "error");
    }
  }, [showStatus]);

  const handleCancelAll = useCallback(() => {
    setCancelAllOpen(true);
  }, []);

  const confirmCancelAll = useCallback(async () => {
    setCancelAllOpen(false);
    showStatus("Cancelling…", "pending", 0);
    try {
      await cancelAllOrders("FlintScalper");
      showStatus("All orders cancelled", "success");
    } catch (err) {
      showStatus(err instanceof Error ? err.message : "Cancel failed", "error");
    }
  }, [showStatus]);

  // Keyboard shortcuts — only when focused
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (!focused || !e.shiftKey) return;
      switch (e.key) {
        case "ArrowLeft":
          e.preventDefault();
          handleOrder(ceSymbol, optExch, "SELL");
          break;
        case "ArrowUp":
          e.preventDefault();
          handleOrder(ceSymbol, optExch, "BUY");
          break;
        case "ArrowRight":
          e.preventDefault();
          handleOrder(peSymbol, optExch, "SELL");
          break;
        case "ArrowDown":
          e.preventDefault();
          handleOrder(peSymbol, optExch, "BUY");
          break;
        case "Escape":
          e.preventDefault();
          setPendingOrder(null);
          break;
        default:
          break;
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [focused, ceSymbol, peSymbol, optExch, handleOrder]);

  const chartHeight = 120;

  return (
    <div
      ref={containerRef}
      tabIndex={0}
      onFocus={() => setFocused(true)}
      onBlur={(e) => {
        if (!containerRef.current?.contains(e.relatedTarget as Node)) setFocused(false);
      }}
      className="h-full flex flex-col bg-surface-base text-text-primary focus:outline-none overflow-hidden"
    >
      {/* ── CONTROL BAR ── */}
      <div className="shrink-0 bg-surface-card border-b border-border-default">
        <div className="flex items-end gap-3 px-3 py-2 flex-wrap">
          {/* Index selector */}
          <div className="flex flex-col gap-0.5">
            <span className="text-xxs text-text-muted uppercase tracking-wider font-sans">Index</span>
            <Select value={symbol} onValueChange={setSymbol}>
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
              <button
                type="button"
                onClick={() => void fetchExpiries()}
                className="h-8 flex items-center gap-1.5 px-2 text-xs font-mono text-loss border border-loss/30 rounded-md bg-loss/5 hover:bg-loss/10 transition-colors"
              >
                <AlertTriangle size={10} />
                Failed to load
                <RefreshCw size={10} />
              </button>
            ) : (
              <Select
                value={expiry}
                onValueChange={setExpiry}
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
            onDec={() => setCeOffset((o) => o - 1)}
            onInc={() => setCeOffset((o) => o + 1)}
          />

          {/* PE Strike stepper */}
          <Stepper
            label="PE Strike"
            value={peStrike != null ? `${peStrike}` : "—"}
            onDec={() => setPeOffset((o) => o - 1)}
            onInc={() => setPeOffset((o) => o + 1)}
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

        {/* Row 2: Lots, Product, OrderType, Interval, SL, Target, One-click */}
        <div className="flex items-end gap-3 px-3 py-2 border-t border-border-subtle flex-wrap">
          {/* Lot spinner — large */}
          <Stepper
            label={`Lot`}
            sublabel={`×${lotSize}`}
            value={`${lots} (${lots * lotSize})`}
            onDec={() => setLots((l) => Math.max(1, l - 1))}
            onInc={() => setLots((l) => l + 1)}
            large
          />

          {/* Product toggle */}
          <ToggleGroup
            label="Product"
            value={product}
            options={["MIS", "NRML"] as const}
            onChange={(v) => setProduct(v as ProductType)}
          />

          {/* Order type toggle */}
          <ToggleGroup
            label="Type"
            value={orderType}
            options={["MARKET", "LIMIT"] as const}
            onChange={(v) => setOrderType(v as OrderTypeValue)}
          />

          {/* Timeframe buttons */}
          <ToggleGroup
            label="Timeframe"
            value={interval}
            options={["1m", "3m", "5m", "15m"] as const}
            onChange={(v) => setInterval_(v as IntervalValue)}
          />

          {/* SL input */}
          <NumberInput label="SL" value={sl} onChange={setSl} min={0} placeholder="pts" />

          {/* Target input */}
          <NumberInput label="Target" value={target} onChange={setTarget} min={0} placeholder="pts" />

          <div className="flex-1" />

          {/* 1-CLICK toggle */}
          <div className="flex flex-col gap-0.5">
            <span className="text-xxs text-text-muted uppercase tracking-wider font-sans">Mode</span>
            <button
              type="button"
              onClick={() => setOneClick((v) => !v)}
              title={oneClick ? "One-click ON — click to disable" : "One-click OFF — click to enable"}
              className={`flex items-center gap-1.5 px-4 h-8 rounded-md font-semibold text-sm transition-colors ${
                oneClick
                  ? "bg-accent text-white shadow-sm"
                  : "bg-surface-hover border border-border-default text-text-muted hover:text-text-primary"
              }`}
            >
              {oneClick ? <Zap size={14} /> : <ZapOff size={14} />}
              {oneClick ? "1-CLICK ON" : "1-CLICK"}
            </button>
          </div>
        </div>
      </div>

      {/* ── 3-PANEL CHART AREA ── */}
      <div className="flex-1 flex min-h-0 overflow-hidden">
        {/* CE PANEL */}
        <div
          className="flex flex-col border-r border-border-default"
          style={{ width: "28%", minWidth: 0 }}
        >
          {/* CE header */}
          <div className="shrink-0 px-3 py-2 bg-surface-card border-b border-border-subtle">
            <div className="flex items-center justify-between mb-1">
              <span className="text-xs font-mono text-profit font-bold uppercase tracking-wider">
                {ceSymbol ?? `${symbol} CE`}
              </span>
              <span className="text-xxs text-text-disabled font-sans uppercase">Call</span>
            </div>
            <LtpBlock
              label="LTP"
              symbol={ceSymbol ?? ""}
              exchange={optExch}
              ticks={ticks}
            />
          </div>

          {/* CE chart */}
          <div className="flex-1 overflow-hidden min-h-0">
            {ceSymbol ? (
              <Chart
                symbol={ceSymbol}
                exchange={optExch}
                interval={interval}
                height={chartHeight}
                className="h-full"
              />
            ) : (
              <div className="h-full flex items-center justify-center text-xs text-text-muted font-sans">
                Select expiry
              </div>
            )}
          </div>

          {/* CE action buttons */}
          <div className="shrink-0 flex border-t border-border-default">
            <ActionButton
              onClick={() => handleOrder(ceSymbol, optExch, "SELL")}
              disabled={!ceSymbol}
              title="Sell CE (Shift+←)"
              variant="sell"
              icon={<TrendingDown size={14} />}
              label="Sell CE"
              shortcut="Shift + ←"
            />
            <ActionButton
              onClick={() => handleOrder(ceSymbol, optExch, "BUY")}
              disabled={!ceSymbol}
              title="Buy CE (Shift+↑)"
              variant="buy"
              icon={<TrendingUp size={14} />}
              label="Buy CE"
              shortcut="Shift + ↑"
            />
          </div>
        </div>

        {/* SPOT PANEL */}
        <div className="flex flex-col" style={{ width: "44%", minWidth: 0 }}>
          {/* Spot header / info panel */}
          <div className="shrink-0 px-3 py-2 bg-surface-card border-b border-border-subtle">
            <div className="flex items-center justify-between mb-1">
              <div className="flex items-baseline gap-2">
                <span className="text-sm font-heading font-bold text-text-primary">
                  {symbol}
                </span>
                <span className="text-xxs text-text-disabled font-sans uppercase">{spotExch}</span>
              </div>
              <span className="text-xs font-mono text-text-primary uppercase">Spot</span>
            </div>
            <div className="flex items-center gap-4">
              <LtpBlock label="LTP" symbol={symbol} exchange={spotExch} ticks={ticks} />
              {atmStrike != null && (
                <div className="flex items-baseline gap-1">
                  <span className="text-xxs text-text-muted uppercase tracking-wider font-sans">ATM</span>
                  <span className="font-mono text-sm font-bold text-accent">{fmtInt(atmStrike)}</span>
                </div>
              )}
            </div>
          </div>

          {/* Spot chart */}
          <div className="flex-1 overflow-hidden min-h-0">
            <Chart
              symbol={symbol}
              exchange={spotExch}
              interval={interval}
              height={chartHeight}
              className="h-full"
            />
          </div>

          {/* Center action buttons: Close All / Cancel All */}
          <div className="shrink-0 flex border-t border-border-default">
            <ActionButton
              onClick={() => void handleCloseAll()}
              title="Close all positions (F6)"
              variant="warning"
              icon={<X size={14} />}
              label="Close All"
              shortcut="F6"
            />
            <ActionButton
              onClick={() => void handleCancelAll()}
              title="Cancel all orders (F7)"
              variant="neutral"
              icon={<RefreshCw size={14} />}
              label="Cancel All"
              shortcut="F7"
            />
          </div>
        </div>

        {/* PE PANEL */}
        <div
          className="flex flex-col border-l border-border-default"
          style={{ width: "28%", minWidth: 0 }}
        >
          {/* PE header */}
          <div className="shrink-0 px-3 py-2 bg-surface-card border-b border-border-subtle">
            <div className="flex items-center justify-between mb-1">
              <span className="text-xs font-mono text-loss font-bold uppercase tracking-wider">
                {peSymbol ?? `${symbol} PE`}
              </span>
              <span className="text-xxs text-text-disabled font-sans uppercase">Put</span>
            </div>
            <LtpBlock
              label="LTP"
              symbol={peSymbol ?? ""}
              exchange={optExch}
              ticks={ticks}
            />
          </div>

          {/* PE chart */}
          <div className="flex-1 overflow-hidden min-h-0">
            {peSymbol ? (
              <Chart
                symbol={peSymbol}
                exchange={optExch}
                interval={interval}
                height={chartHeight}
                className="h-full"
              />
            ) : (
              <div className="h-full flex items-center justify-center text-xs text-text-muted font-sans">
                Select expiry
              </div>
            )}
          </div>

          {/* PE action buttons */}
          <div className="shrink-0 flex border-t border-border-default">
            <ActionButton
              onClick={() => handleOrder(peSymbol, optExch, "BUY")}
              disabled={!peSymbol}
              title="Buy Put (Shift+↓)"
              variant="buy"
              icon={<TrendingUp size={14} />}
              label="Buy PE"
              shortcut="Shift + ↓"
            />
            <ActionButton
              onClick={() => handleOrder(peSymbol, optExch, "SELL")}
              disabled={!peSymbol}
              title="Sell Put (Shift+→)"
              variant="sell"
              icon={<TrendingDown size={14} />}
              label="Sell PE"
              shortcut="Shift + →"
            />
          </div>
        </div>
      </div>

      {/* ── ORDER CONFIRMATION MODAL (non-one-click) ── */}
      {pendingOrder && (
        <div role="dialog" aria-modal="true" aria-labelledby="scalper-confirm-title" className="absolute inset-0 flex items-center justify-center bg-surface-base/80 backdrop-blur-sm z-50">
          <div className="bg-surface-card border border-border-default rounded-lg p-4 min-w-64 shadow-2xl">
            <div id="scalper-confirm-title" className="text-sm font-heading font-bold text-text-primary mb-3">Confirm Order</div>
            <div className="space-y-1.5 mb-4">
              <div className="flex justify-between text-xs">
                <span className="text-text-muted font-sans">Symbol</span>
                <span className="font-mono font-bold text-text-primary">{pendingOrder.sym}</span>
              </div>
              <div className="flex justify-between text-xs">
                <span className="text-text-muted font-sans">Action</span>
                <span
                  className={`font-semibold ${
                    pendingOrder.action === "BUY" ? "text-profit" : "text-loss"
                  }`}
                >
                  {pendingOrder.action}
                </span>
              </div>
              <div className="flex justify-between text-xs">
                <span className="text-text-muted font-sans">Qty</span>
                <span className="font-mono font-bold text-text-primary">
                  {lots * lotSize} ({lots} lot{lots > 1 ? "s" : ""})
                </span>
              </div>
              <div className="flex justify-between text-xs">
                <span className="text-text-muted font-sans">Product</span>
                <span className="font-mono text-text-primary">
                  {product} · {orderType}
                </span>
              </div>
              {sl && (
                <div className="flex justify-between text-xs">
                  <span className="text-text-muted font-sans">SL</span>
                  <span className="font-mono text-loss">{sl} pts</span>
                </div>
              )}
              {target && (
                <div className="flex justify-between text-xs">
                  <span className="text-text-muted font-sans">Target</span>
                  <span className="font-mono text-profit">{target} pts</span>
                </div>
              )}
            </div>
            <div className="flex gap-2">
              <button
                ref={confirmBtnRef}
                type="button"
                onClick={confirmOrder}
                className={`flex-1 h-8 rounded-md text-sm font-semibold transition-colors ${
                  pendingOrder.action === "BUY"
                    ? "bg-profit hover:bg-profit/80 text-white"
                    : "bg-loss hover:bg-loss/80 text-white"
                }`}
              >
                Confirm {pendingOrder.action}
              </button>
              <button
                type="button"
                onClick={() => setPendingOrder(null)}
                className="flex-1 h-8 rounded-md text-sm font-medium bg-surface-hover hover:bg-surface-card text-text-secondary border border-border-default transition-colors"
              >
                Cancel (Esc)
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Close all positions confirmation */}
      <AlertDialog open={closeAllOpen} onOpenChange={setCloseAllOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Close all open positions?</AlertDialogTitle>
            <AlertDialogDescription>
              This will send a close request for all positions under the FlintScalper
              strategy. This cannot be undone.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => void confirmCloseAll()}
              className="bg-loss hover:bg-loss/90 text-white"
            >
              Close All Positions
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {/* Cancel all pending orders confirmation */}
      <AlertDialog open={cancelAllOpen} onOpenChange={setCancelAllOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Cancel all pending orders?</AlertDialogTitle>
            <AlertDialogDescription>
              All pending orders under the FlintScalper strategy will be cancelled.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Keep Orders</AlertDialogCancel>
            <AlertDialogAction onClick={() => void confirmCancelAll()}>
              Cancel All Orders
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}

export default memo(ScalperWidget);
