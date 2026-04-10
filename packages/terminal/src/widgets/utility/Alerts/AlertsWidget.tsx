/**
 * AlertsWidget — Price alert management for FlintTrade terminal.
 *
 * Features:
 *   - Two tabs: Active Alerts | Alert Log
 *   - Create alerts with symbol autocomplete, condition dropdown, target price
 *   - Alerts persisted to localStorage (`flinttrade:alerts`)
 *   - LTP polling via OpenAlgo REST (5s market hours, 60s off-hours)
 *   - Auto-transitions armed → triggered when price condition is met
 *   - Compact Dockview-panel layout using FlintTrade design tokens
 */

import { useState, useEffect, useCallback, useRef, useMemo, memo } from "react";
import {
  Bell,
  BellRing,
  ArrowUp,
  ArrowDown,
  Trash2,
  Plus,
  Clock,
  X,
  Search,
  ChevronDown,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { cn } from "@/lib/utils";
import { searchSymbol, getTicker } from "@/services/api";
import { isMarketHours } from "@/lib/market";
import { useTrackBehavior } from "@/hooks/useTrackBehavior";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface PriceAlert {
  id: string;
  symbol: string;
  exchange: string;
  condition: "above" | "below" | "crosses_above" | "crosses_below";
  targetPrice: number;
  createdAt: string;
  triggeredAt?: string;
  status: "armed" | "triggered" | "expired";
}

type AlertTab = "active" | "log";

type AlertCondition = PriceAlert["condition"];

interface SearchResult {
  symbol: string;
  exchange: string;
  name?: string;
}

interface LtpMap {
  [key: string]: number;
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const LS_KEY = "flinttrade:alerts";

const CONDITION_LABELS: Record<AlertCondition, string> = {
  above: "Above",
  below: "Below",
  crosses_above: "Crosses Above",
  crosses_below: "Crosses Below",
};

// ---------------------------------------------------------------------------
// Formatters
// ---------------------------------------------------------------------------

const FMT = new Intl.NumberFormat("en-IN", {
  maximumFractionDigits: 2,
  minimumFractionDigits: 2,
});

function fmtPrice(v: number | null | undefined): string {
  if (v == null || isNaN(v)) return "—";
  return FMT.format(Number(v));
}

function fmtTime(iso: string): string {
  try {
    return new Date(iso).toLocaleTimeString("en-IN", {
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
      timeZone: "Asia/Kolkata",
    });
  } catch {
    return "—";
  }
}

function fmtDate(iso: string): string {
  try {
    return new Date(iso).toLocaleDateString("en-IN", {
      day: "2-digit",
      month: "short",
      timeZone: "Asia/Kolkata",
    });
  } catch {
    return "—";
  }
}

// ---------------------------------------------------------------------------
// localStorage helpers
// ---------------------------------------------------------------------------

function loadAlerts(): PriceAlert[] {
  try {
    const raw = localStorage.getItem(LS_KEY);
    if (raw) {
      const parsed: unknown = JSON.parse(raw);
      if (Array.isArray(parsed)) return parsed as PriceAlert[];
    }
  } catch {
    // ignore parse errors
  }
  return [];
}

function saveAlerts(alerts: PriceAlert[]): void {
  try {
    localStorage.setItem(LS_KEY, JSON.stringify(alerts));
  } catch {
    // localStorage unavailable
  }
}

function generateId(): string {
  return `alert-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
}

// ---------------------------------------------------------------------------
// Alert condition check
// ---------------------------------------------------------------------------

function isTriggered(
  alert: PriceAlert,
  currentLtp: number,
  prevLtp: number | null,
): boolean {
  const { condition, targetPrice } = alert;

  switch (condition) {
    case "above":
      return currentLtp > targetPrice;
    case "below":
      return currentLtp < targetPrice;
    case "crosses_above":
      return prevLtp != null && prevLtp <= targetPrice && currentLtp > targetPrice;
    case "crosses_below":
      return prevLtp != null && prevLtp >= targetPrice && currentLtp < targetPrice;
    default:
      return false;
  }
}

// ---------------------------------------------------------------------------
// Condition icon
// ---------------------------------------------------------------------------

function ConditionIcon({ condition }: { condition: AlertCondition }) {
  switch (condition) {
    case "above":
    case "crosses_above":
      return <ArrowUp className="size-3 text-profit shrink-0" aria-hidden="true" />;
    case "below":
    case "crosses_below":
      return <ArrowDown className="size-3 text-loss shrink-0" aria-hidden="true" />;
  }
}

// ---------------------------------------------------------------------------
// Symbol search dropdown
// ---------------------------------------------------------------------------

interface SymbolSearchProps {
  value: string;
  exchange: string;
  onSelect: (symbol: string, exchange: string) => void;
}

function SymbolSearch({ value, exchange, onSelect }: SymbolSearchProps) {
  const [query, setQuery] = useState(value);
  const [results, setResults] = useState<SearchResult[]>([]);
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const containerRef = useRef<HTMLDivElement | null>(null);

  // Sync external value changes (e.g., reset)
  useEffect(() => {
    setQuery(value);
  }, [value]);

  const handleQuery = useCallback((val: string) => {
    setQuery(val);
    if (debounceRef.current) clearTimeout(debounceRef.current);

    if (!val.trim()) {
      setResults([]);
      setOpen(false);
      return;
    }

    debounceRef.current = setTimeout(async () => {
      setLoading(true);
      try {
        const data = await searchSymbol(val.trim());
        setResults(Array.isArray(data) ? (data as SearchResult[]).slice(0, 10) : []);
        setOpen(true);
      } catch {
        setResults([]);
      } finally {
        setLoading(false);
      }
    }, 300);
  }, []);

  useEffect(
    () => () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    },
    [],
  );

  // Close on outside click
  useEffect(() => {
    if (!open) return;
    function handle(e: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handle);
    return () => document.removeEventListener("mousedown", handle);
  }, [open]);

  const handleSelect = useCallback(
    (item: SearchResult) => {
      setQuery(item.symbol);
      setOpen(false);
      setResults([]);
      onSelect(item.symbol, item.exchange);
    },
    [onSelect],
  );

  return (
    <div ref={containerRef} className="relative">
      <div className="relative">
        <Search className="absolute left-2 top-1/2 -translate-y-1/2 size-3 text-text-muted pointer-events-none" />
        <Input
          value={query}
          onChange={(e) => handleQuery(e.target.value)}
          placeholder="Symbol…"
          className="pl-6 h-7 text-xs font-mono bg-surface-base border-border-default text-text-primary placeholder:text-text-muted focus-visible:ring-accent/40"
          aria-label="Symbol search"
          aria-autocomplete="list"
          aria-expanded={open}
          onFocus={() => query.trim() && results.length > 0 && setOpen(true)}
        />
        {loading && (
          <span className="absolute right-2 top-1/2 -translate-y-1/2 text-xxs text-text-muted">
            …
          </span>
        )}
      </div>

      {open && results.length > 0 && (
        <div
          role="listbox"
          aria-label="Symbol suggestions"
          className="absolute z-50 left-0 right-0 top-full mt-0.5 bg-surface-card border border-border-default rounded shadow-2xl max-h-44 overflow-auto"
        >
          {results.map((item) => (
            <button
              key={`${item.symbol}-${item.exchange}`}
              role="option"
              aria-selected={item.symbol === value && item.exchange === exchange}
              onClick={() => handleSelect(item)}
              className="w-full flex items-center justify-between px-2.5 py-1.5 hover:bg-surface-hover text-left transition-colors border-b border-border-subtle last:border-none"
            >
              <span className="text-xs font-mono font-medium text-text-primary">
                {item.symbol}
              </span>
              <span className="text-xxs text-text-muted font-mono ml-2 shrink-0">
                {item.exchange}
              </span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Create alert form (inline)
// ---------------------------------------------------------------------------

interface CreateAlertFormProps {
  onSubmit: (alert: Omit<PriceAlert, "id" | "createdAt" | "status">) => void;
  onCancel: () => void;
}

function CreateAlertForm({ onSubmit, onCancel }: CreateAlertFormProps) {
  const [symbol, setSymbol] = useState("");
  const [exchange, setExchange] = useState("");
  const [condition, setCondition] = useState<AlertCondition>("above");
  const [targetPrice, setTargetPrice] = useState("");
  const [error, setError] = useState<string | null>(null);

  const handleSymbolSelect = useCallback((sym: string, exch: string) => {
    setSymbol(sym);
    setExchange(exch);
    setError(null);
  }, []);

  const handleSubmit = useCallback(
    (e: React.FormEvent) => {
      e.preventDefault();

      if (!symbol.trim()) {
        setError("Symbol is required");
        return;
      }
      if (!exchange.trim()) {
        setError("Select a valid symbol from the list");
        return;
      }
      const price = parseFloat(targetPrice);
      if (isNaN(price) || price <= 0) {
        setError("Enter a valid target price");
        return;
      }

      onSubmit({ symbol, exchange, condition, targetPrice: price });
    },
    [symbol, exchange, condition, targetPrice, onSubmit],
  );

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === "Escape") onCancel();
    },
    [onCancel],
  );

  return (
    <form
      onSubmit={handleSubmit}
      onKeyDown={handleKeyDown}
      className="px-2 py-2 border-b border-border-default bg-surface-card space-y-2"
      aria-label="Create price alert"
    >
      <div className="flex items-center justify-between mb-1">
        <span className="text-xs font-semibold text-text-secondary">New Alert</span>
        <button
          type="button"
          onClick={onCancel}
          className="text-text-muted hover:text-text-primary transition-colors"
          aria-label="Cancel"
        >
          <X className="size-3" />
        </button>
      </div>

      {/* Symbol search */}
      <SymbolSearch value={symbol} exchange={exchange} onSelect={handleSymbolSelect} />

      {/* Condition + Target price row */}
      <div className="flex gap-1.5">
        <div className="flex-1 min-w-0">
          <Select
            value={condition}
            onValueChange={(v) => setCondition(v as AlertCondition)}
          >
            <SelectTrigger
              className="h-7 text-xs bg-surface-base border-border-default text-text-primary focus:ring-accent/40"
              aria-label="Alert condition"
            >
              <SelectValue />
              <ChevronDown className="size-3 opacity-50 ml-1 shrink-0" />
            </SelectTrigger>
            <SelectContent className="bg-surface-card border-border-default">
              {(Object.keys(CONDITION_LABELS) as AlertCondition[]).map((key) => (
                <SelectItem
                  key={key}
                  value={key}
                  className="text-xs text-text-primary focus:bg-surface-hover"
                >
                  {CONDITION_LABELS[key]}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        <Input
          type="number"
          value={targetPrice}
          onChange={(e) => setTargetPrice(e.target.value)}
          placeholder="Target ₹"
          step="0.05"
          min="0"
          className="w-24 h-7 text-xs font-mono bg-surface-base border-border-default text-text-primary placeholder:text-text-muted focus-visible:ring-accent/40"
          aria-label="Target price"
        />
      </div>

      {error && (
        <p role="alert" className="text-xxs text-loss">
          {error}
        </p>
      )}

      <div className="flex justify-end gap-1.5">
        <Button
          type="button"
          variant="ghost"
          size="sm"
          onClick={onCancel}
          className="h-6 px-2.5 text-xxs text-text-muted hover:text-text-primary"
        >
          Cancel
        </Button>
        <Button
          type="submit"
          size="sm"
          className="h-6 px-2.5 text-xxs bg-accent text-white hover:bg-accent/90"
        >
          Set Alert
        </Button>
      </div>
    </form>
  );
}

// ---------------------------------------------------------------------------
// Alert row (Active tab)
// ---------------------------------------------------------------------------

interface AlertRowProps {
  alert: PriceAlert;
  ltp: number | null;
  onDelete: (id: string) => void;
}

function AlertRow({ alert, ltp, onDelete }: AlertRowProps) {
  const isTriggeredStatus = alert.status === "triggered";
  const isExpiredStatus = alert.status === "expired";

  const conditionColor =
    alert.condition === "above" || alert.condition === "crosses_above"
      ? "text-profit"
      : "text-loss";

  const ltpColor =
    ltp == null
      ? "text-text-muted"
      : ltp > alert.targetPrice
        ? "text-profit"
        : ltp < alert.targetPrice
          ? "text-loss"
          : "text-text-primary";

  return (
    <div
      role="listitem"
      className={cn(
        "flex items-center gap-2 px-2 py-1.5 border-b border-border-subtle transition-colors group",
        isTriggeredStatus && "bg-profit/5",
        isExpiredStatus && "opacity-50",
        !isTriggeredStatus && !isExpiredStatus && "hover:bg-surface-hover",
      )}
    >
      {/* Status icon */}
      <span className="shrink-0" aria-label={`Status: ${alert.status}`}>
        {isTriggeredStatus ? (
          <BellRing className="size-3 text-profit" />
        ) : isExpiredStatus ? (
          <Bell className="size-3 text-text-muted" />
        ) : (
          <Bell className="size-3 text-accent" />
        )}
      </span>

      {/* Symbol badge */}
      <span
        className="shrink-0 text-xxs font-mono font-semibold bg-surface-card border border-border-default rounded px-1.5 py-0.5 text-text-primary"
        aria-label={`Symbol: ${alert.symbol}`}
      >
        {alert.symbol}
      </span>

      {/* Condition */}
      <ConditionIcon condition={alert.condition} />
      <span
        className={cn("text-xxs font-medium shrink-0", conditionColor)}
        aria-label={`Condition: ${CONDITION_LABELS[alert.condition]}`}
      >
        {CONDITION_LABELS[alert.condition]}
      </span>

      {/* Target price */}
      <span
        className="text-xs font-mono tabular-nums text-text-primary shrink-0"
        aria-label={`Target price: ${fmtPrice(alert.targetPrice)}`}
      >
        {fmtPrice(alert.targetPrice)}
      </span>

      <div className="flex-1" />

      {/* Current LTP */}
      <span
        className={cn("text-xs font-mono tabular-nums shrink-0", ltpColor)}
        aria-label={`Current price: ${fmtPrice(ltp)}`}
      >
        {fmtPrice(ltp)}
      </span>

      {/* Delete button */}
      <button
        onClick={() => onDelete(alert.id)}
        className="opacity-0 group-hover:opacity-100 focus:opacity-100 shrink-0 text-text-muted hover:text-loss transition-all"
        aria-label={`Delete alert for ${alert.symbol}`}
        title="Delete alert"
      >
        <Trash2 className="size-3" />
      </button>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Log row (Alert Log tab)
// ---------------------------------------------------------------------------

interface LogRowProps {
  alert: PriceAlert;
  onDelete: (id: string) => void;
}

function LogRow({ alert, onDelete }: LogRowProps) {
  return (
    <div
      role="listitem"
      className="flex items-center gap-2 px-2 py-1.5 border-b border-border-subtle hover:bg-surface-hover transition-colors group"
    >
      {/* Status icon */}
      <BellRing className="size-3 text-profit shrink-0" aria-hidden="true" />

      {/* Symbol */}
      <span className="text-xxs font-mono font-semibold text-text-primary shrink-0">
        {alert.symbol}
      </span>

      {/* Condition summary */}
      <ConditionIcon condition={alert.condition} />
      <span className="text-xxs text-text-secondary shrink-0 font-mono">
        {fmtPrice(alert.targetPrice)}
      </span>

      <div className="flex-1" />

      {/* Triggered timestamp */}
      {alert.triggeredAt && (
        <div className="flex items-center gap-1 text-xxs text-text-muted shrink-0">
          <Clock className="size-3" aria-hidden="true" />
          <span className="font-mono" title={alert.triggeredAt}>
            {fmtDate(alert.triggeredAt)} {fmtTime(alert.triggeredAt)}
          </span>
        </div>
      )}

      {/* Delete button */}
      <button
        onClick={() => onDelete(alert.id)}
        className="opacity-0 group-hover:opacity-100 focus:opacity-100 shrink-0 text-text-muted hover:text-loss transition-all"
        aria-label={`Remove log entry for ${alert.symbol}`}
        title="Remove log entry"
      >
        <Trash2 className="size-3" />
      </button>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Empty states
// ---------------------------------------------------------------------------

function EmptyActive({ onCreateClick }: { onCreateClick: () => void }) {
  return (
    <div className="h-full flex flex-col items-center justify-center gap-3 px-4">
      <Bell className="size-6 text-text-muted" aria-hidden="true" />
      <div className="text-center">
        <p className="text-xs text-text-secondary">No active alerts</p>
        <p className="text-xs text-text-muted mt-0.5">
          Get notified when prices hit your targets
        </p>
      </div>
      <button
        onClick={onCreateClick}
        className="flex items-center gap-1.5 px-3 py-1.5 bg-accent/10 hover:bg-accent/20 text-accent border border-accent/30 rounded text-xs font-medium transition-colors"
      >
        <Plus className="size-3" />
        Create Alert
      </button>
    </div>
  );
}

function EmptyLog() {
  return (
    <div className="h-full flex flex-col items-center justify-center gap-2 px-4">
      <Clock className="size-6 text-text-muted" aria-hidden="true" />
      <p className="text-xs text-text-secondary">No triggered alerts yet</p>
      <p className="text-xs text-text-muted">Triggered alerts will appear here</p>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main widget
// ---------------------------------------------------------------------------

function AlertsWidget() {
  const track = useTrackBehavior();

  const [alerts, setAlerts] = useState<PriceAlert[]>(() => loadAlerts());
  const [activeTab, setActiveTab] = useState<AlertTab>("active");
  const [showForm, setShowForm] = useState(false);
  const [ltpMap, setLtpMap] = useState<LtpMap>({});
  const prevLtpRef = useRef<LtpMap>({});
  const pollRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Track widget usage on mount
  useEffect(() => {
    track("trade", "widgetsUsed");
  }, [track]);

  // Persist alerts to localStorage whenever they change
  useEffect(() => {
    saveAlerts(alerts);
  }, [alerts]);

  // ---------------------------------------------------------------------------
  // LTP polling
  // ---------------------------------------------------------------------------

  const armedAlerts = useMemo(
    () => alerts.filter((a) => a.status === "armed"),
    [alerts],
  );

  const fetchLtps = useCallback(async () => {
    if (armedAlerts.length === 0) return;

    // Collect only new values — do NOT start from ltpMap snapshot to avoid
    // stale closure. We merge into current state via the functional updater.
    const freshEntries: LtpMap = {};

    await Promise.allSettled(
      armedAlerts.map(async (alert) => {
        const key = `${alert.exchange}:${alert.symbol}`;
        try {
          const quote = await getTicker(alert.symbol, alert.exchange);
          const ltp = quote?.ltp ?? null;
          if (ltp != null) freshEntries[key] = Number(ltp);
        } catch {
          // network failure — keep previous LTP
        }
      }),
    );

    const prev = prevLtpRef.current;

    // Build the merged map once so trigger-check and state update use the same values
    const merged: LtpMap = { ...prev, ...freshEntries };
    prevLtpRef.current = merged;

    // Check triggers
    setAlerts((prevAlerts) => {
      let changed = false;
      const updated = prevAlerts.map((alert) => {
        if (alert.status !== "armed") return alert;
        const key = `${alert.exchange}:${alert.symbol}`;
        const currentLtp = merged[key];
        if (currentLtp == null) return alert;
        const prevLtp = prev[key] ?? null;
        if (isTriggered(alert, currentLtp, prevLtp)) {
          changed = true;
          return {
            ...alert,
            status: "triggered" as const,
            triggeredAt: new Date().toISOString(),
          };
        }
        return alert;
      });
      return changed ? updated : prevAlerts;
    });

    // Merge fresh entries into existing ltpMap without requiring ltpMap in deps
    setLtpMap((prev) => ({ ...prev, ...freshEntries }));
  }, [armedAlerts]);

  // Stable ref so the scheduler does not rebuild on ltpMap change
  const fetchLtpsRef = useRef(fetchLtps);
  useEffect(() => {
    fetchLtpsRef.current = fetchLtps;
  }, [fetchLtps]);

  useEffect(() => {
    if (armedAlerts.length === 0) return;

    void fetchLtpsRef.current();

    function schedule() {
      const delay = isMarketHours() ? 5000 : 60000;
      pollRef.current = setTimeout(() => {
        void fetchLtpsRef.current();
        schedule();
      }, delay);
    }

    schedule();

    return () => {
      if (pollRef.current) clearTimeout(pollRef.current);
    };
    // Re-schedule when the set of armed alerts changes (symbol added/removed)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [armedAlerts.length]);

  // ---------------------------------------------------------------------------
  // CRUD
  // ---------------------------------------------------------------------------

  const handleCreate = useCallback(
    (partial: Omit<PriceAlert, "id" | "createdAt" | "status">) => {
      const alert: PriceAlert = {
        ...partial,
        id: generateId(),
        createdAt: new Date().toISOString(),
        status: "armed",
      };
      setAlerts((prev) => [alert, ...prev]);
      setShowForm(false);
    },
    [],
  );

  const handleDelete = useCallback((id: string) => {
    setAlerts((prev) => prev.filter((a) => a.id !== id));
  }, []);

  // ---------------------------------------------------------------------------
  // Derived lists
  // ---------------------------------------------------------------------------

  const activeAlerts = useMemo(
    () => alerts.filter((a) => a.status === "armed" || a.status === "triggered"),
    [alerts],
  );

  const logAlerts = useMemo(
    () =>
      alerts
        .filter((a) => a.status === "triggered" || a.status === "expired")
        .sort((x, y) => {
          const tx = x.triggeredAt ?? x.createdAt;
          const ty = y.triggeredAt ?? y.createdAt;
          return ty.localeCompare(tx);
        }),
    [alerts],
  );

  const armedCount = useMemo(
    () => alerts.filter((a) => a.status === "armed").length,
    [alerts],
  );

  const triggeredCount = useMemo(
    () => alerts.filter((a) => a.status === "triggered").length,
    [alerts],
  );

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  return (
    <div className="h-full flex flex-col bg-surface-base text-text-primary overflow-hidden">
      {/* Header */}
      <div className="flex items-center gap-1.5 px-2 py-1 border-b border-border-default bg-surface-card shrink-0">
        <Bell className="size-3.5 text-accent shrink-0" aria-hidden="true" />
        <span className="font-heading font-semibold text-sm text-text-secondary uppercase tracking-wider">
          Price Alerts
        </span>

        {armedCount > 0 && (
          <span
            className="text-xxs font-mono bg-accent/10 text-accent border border-accent/30 rounded px-1 leading-4"
            aria-label={`${armedCount} armed alerts`}
          >
            {armedCount}
          </span>
        )}

        {triggeredCount > 0 && (
          <span
            className="text-xxs font-mono bg-profit/10 text-profit border border-profit/30 rounded px-1 leading-4"
            aria-label={`${triggeredCount} triggered alerts`}
          >
            {triggeredCount}
          </span>
        )}

        <div className="flex-1" />

        <Button
          variant="ghost"
          size="sm"
          onClick={() => setShowForm((v) => !v)}
          className="h-5 w-5 p-0 text-text-muted hover:text-text-primary hover:bg-surface-hover"
          aria-label="Create alert"
          title="Create new price alert"
        >
          <Plus className="size-3" />
        </Button>
      </div>

      {/* Inline create form */}
      {showForm && (
        <CreateAlertForm
          onSubmit={handleCreate}
          onCancel={() => setShowForm(false)}
        />
      )}

      {/* Tab bar */}
      <div
        role="tablist"
        aria-label="Alerts tabs"
        className="flex items-end gap-0 px-2 border-b border-border-default bg-surface-card shrink-0"
      >
        {(["active", "log"] as AlertTab[]).map((tab) => {
          const isActive = activeTab === tab;
          return (
            <button
              key={tab}
              role="tab"
              id={`alerts-tab-${tab}`}
              aria-selected={isActive}
              aria-controls={`alerts-panel-${tab}`}
              aria-current={isActive ? "true" : undefined}
              onClick={() => setActiveTab(tab)}
              className={cn(
                "flex items-center gap-1 px-2.5 py-1.5 text-xxs font-medium transition-colors border-b-2 whitespace-nowrap shrink-0",
                isActive
                  ? "text-accent border-accent"
                  : "text-text-muted hover:text-text-primary border-transparent hover:border-border-default",
              )}
            >
              {tab === "active" ? (
                <>
                  <Bell className="size-3 shrink-0" />
                  Active Alerts
                </>
              ) : (
                <>
                  <Clock className="size-3 shrink-0" />
                  Alert Log
                </>
              )}
            </button>
          );
        })}
      </div>

      {/* Tab content */}
      <div
        role="tabpanel"
        id={`alerts-panel-${activeTab}`}
        aria-labelledby={`alerts-tab-${activeTab}`}
        className="flex-1 overflow-auto"
        aria-label={activeTab === "active" ? "Active alerts" : "Alert log"}
      >
        {activeTab === "active" && (
          <>
            {activeAlerts.length === 0 ? (
              <EmptyActive onCreateClick={() => setShowForm(true)} />
            ) : (
              activeAlerts.map((alert) => {
                const key = `${alert.exchange}:${alert.symbol}`;
                return (
                  <AlertRow
                    key={alert.id}
                    alert={alert}
                    ltp={ltpMap[key] ?? null}
                    onDelete={handleDelete}
                  />
                );
              })
            )}
          </>
        )}

        {activeTab === "log" && (
          <>
            {logAlerts.length === 0 ? (
              <EmptyLog />
            ) : (
              logAlerts.map((alert) => (
                <LogRow key={alert.id} alert={alert} onDelete={handleDelete} />
              ))
            )}
          </>
        )}
      </div>
    </div>
  );
}

export default memo(AlertsWidget);
