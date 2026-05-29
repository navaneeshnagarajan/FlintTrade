import { useState, useEffect } from "react";
import { Info, RefreshCw } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { TableCell, TableRow } from "@/components/ui/table";
import { getExpiry } from "@/services/api";
import type { LiveSelectorState, LiveSymbol } from "./types";
import { LIVE_SYMBOLS } from "./types";

export function ReturnBadge({ value, size = "sm" }: { value: number | null; size?: "sm" | "xs" }) {
  if (value === null) return <span className="text-text-muted">--</span>;
  const isPos = value >= 0;
  const cls = [
    "font-mono font-medium",
    size === "xs" ? "text-xs" : "text-xs",
    isPos ? "text-profit" : "text-loss",
  ].join(" ");
  const formatted = `${value >= 0 ? "+" : ""}${value.toFixed(1)}%`;
  return <span className={cls}>{formatted}</span>;
}

export function DataNotice({ text }: { text?: string }) {
  return (
    <div className="flex items-start gap-2 rounded-md bg-surface-elevated border border-border-default p-3 mb-4">
      <Info size={13} className="text-warning mt-0.5 shrink-0" />
      <p className="text-xs text-text-secondary">
        {text ?? (
          <>
            Live data available during market hours. Connect a data source in{" "}
            <span className="text-primary">Settings</span> for real-time updates.
            Showing representative data structure.
          </>
        )}
      </p>
    </div>
  );
}

export function SectionLabel({ icon: Icon, label }: { icon: LucideIcon; label: string }) {
  return (
    <div className="text-xs text-text-muted mb-2 flex items-center gap-1.5">
      <Icon size={11} />
      {label}
    </div>
  );
}

export function TfButton({
  tf,
  active,
  onClick,
}: {
  tf: string;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className={[
        "text-xs px-2 py-0.5 rounded border transition-colors",
        active
          ? "bg-neutral-bg text-primary border-neutral-border"
          : "bg-surface-card text-text-muted border-border-default hover:border-border-strong",
      ].join(" ")}
    >
      {tf}
    </button>
  );
}

export function LoadingRows({ cols }: { cols: number }) {
  return (
    <>
      {[0, 1, 2, 3, 4].map((i) => (
        <TableRow key={i} className="border-border-default">
          {Array.from({ length: cols }).map((_, j) => (
            <TableCell key={j} className="px-2 py-2">
              <div className="h-3 bg-surface-elevated rounded animate-pulse" />
            </TableCell>
          ))}
        </TableRow>
      ))}
    </>
  );
}

export function ErrorRetry({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 py-12 text-center">
      <p className="text-xs text-loss">{message}</p>
      <button
        onClick={onRetry}
        className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded border border-border-default text-text-secondary hover:text-text-primary hover:border-border-strong transition-colors"
      >
        <RefreshCw size={11} />
        Retry
      </button>
    </div>
  );
}

export function useLiveSelector(defaultSymbol: LiveSymbol = "NIFTY", defaultExchange = "NFO") {
  const [symbol, setSymbol] = useState<LiveSymbol>(defaultSymbol);
  const [exchange, setExchange] = useState(defaultExchange);
  const [expiry, setExpiry] = useState<string | null>(null);
  const [expiries, setExpiries] = useState<string[]>([]);
  const [expiryLoading, setExpiryLoading] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setExpiries([]);
    setExpiry(null);
    setExpiryLoading(true);
    (async () => {
      try {
        const data = await getExpiry(symbol, exchange, "options");
        if (cancelled) return;
        const list: string[] = Array.isArray(data)
          ? (data as string[])
          : ((data as { expiry?: string[] })?.expiry ?? []);
        setExpiries(list);
        setExpiry(list[0] ?? null);
      } catch {
        if (!cancelled) setExpiry(null);
      } finally {
        if (!cancelled) setExpiryLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [symbol, exchange]);

  const state: LiveSelectorState = { symbol, exchange, expiry, expiries, expiryLoading };
  return { state, setSymbol, setExchange, setExpiry };
}

export function LiveSelector({
  state,
  setSymbol,
  setExchange,
  setExpiry,
}: {
  state: LiveSelectorState;
  setSymbol: (s: LiveSymbol) => void;
  setExchange: (e: string) => void;
  setExpiry: (e: string) => void;
}) {
  return (
    <div className="flex flex-wrap items-center gap-2 mb-4">
      <div className="flex items-center gap-1">
        {LIVE_SYMBOLS.map((s) => (
          <button
            key={s}
            onClick={() => setSymbol(s)}
            className={[
              "text-xs px-2 py-0.5 rounded border transition-colors",
              state.symbol === s
                ? "bg-neutral-bg text-primary border-neutral-border"
                : "bg-surface-card text-text-muted border-border-default hover:border-border-strong",
            ].join(" ")}
          >
            {s}
          </button>
        ))}
      </div>
      <div className="flex items-center gap-1">
        {["NFO", "BFO"].map((ex) => (
          <button
            key={ex}
            onClick={() => setExchange(ex)}
            className={[
              "text-xs px-2 py-0.5 rounded border transition-colors",
              state.exchange === ex
                ? "bg-neutral-bg text-primary border-neutral-border"
                : "bg-surface-card text-text-muted border-border-default hover:border-border-strong",
            ].join(" ")}
          >
            {ex}
          </button>
        ))}
      </div>
      {state.expiryLoading ? (
        <span className="text-xs text-text-muted animate-pulse">Loading expiries…</span>
      ) : state.expiries.length > 0 ? (
        <Select value={state.expiry ?? ""} onValueChange={setExpiry}>
          <SelectTrigger className="h-6 w-auto min-w-28 text-xs bg-surface-card text-text-primary border-border-default">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {state.expiries.map((ex) => (
              <SelectItem key={ex} value={ex}>
                {ex}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      ) : null}
    </div>
  );
}
