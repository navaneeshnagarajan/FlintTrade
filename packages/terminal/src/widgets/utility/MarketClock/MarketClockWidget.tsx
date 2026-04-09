/**
 * MarketClockWidget — Live status of major trading sessions in IST.
 *
 * Markets tracked:
 *   - NSE (Equities)        09:15–15:30 IST
 *   - MCX (Commodities)     09:00–23:55 IST
 *   - SGX Nifty             06:30–23:30 IST
 *   - US (NYSE/NASDAQ)      19:00–01:30 IST (next day)
 *   - Europe (LSE/Xetra)    12:30–21:00 IST
 *
 * Features:
 *   - Status: Open (green) / Pre-market (amber) / Closed (grey)
 *   - Progress bar: how far through the session
 *   - Time remaining or time until open
 *   - Ticks every second; uses IST (Asia/Kolkata)
 */

import { useState, useEffect, useMemo, memo } from "react";
import { Clock } from "lucide-react";
import { useTrackBehavior } from "@/hooks/useTrackBehavior";
import { cn } from "@/lib/utils";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type MarketStatus = "open" | "pre" | "closed";

interface MarketDef {
  name: string;
  description: string;
  /** Open time in IST minutes from midnight */
  openMin: number;
  /** Close time in IST minutes from midnight (may exceed 1440 if crosses midnight) */
  closeMin: number;
  /** Pre-market window in minutes before open */
  preMin: number;
}

interface MarketState {
  def: MarketDef;
  status: MarketStatus;
  progress: number;       // 0–1, fraction through session
  remainingMs: number;    // ms until close (open) or until open (closed/pre)
}

// ---------------------------------------------------------------------------
// Market definitions (times in IST minutes)
// ---------------------------------------------------------------------------

function hm(h: number, m: number): number {
  return h * 60 + m;
}

export const MARKET_DEFS: MarketDef[] = [
  {
    name: "NSE",
    description: "India — Equities",
    openMin: hm(9, 15),
    closeMin: hm(15, 30),
    preMin: 15,
  },
  {
    name: "MCX",
    description: "India — Commodities",
    openMin: hm(9, 0),
    closeMin: hm(23, 55),
    preMin: 10,
  },
  {
    name: "SGX Nifty",
    description: "Singapore Exchange",
    openMin: hm(6, 30),
    closeMin: hm(23, 30),
    preMin: 0,
  },
  {
    name: "US Markets",
    description: "NYSE / NASDAQ",
    openMin: hm(19, 0),
    closeMin: hm(25, 30), // 01:30 next day = 25:30
    preMin: 30,
  },
  {
    name: "Europe",
    description: "LSE / Xetra",
    openMin: hm(12, 30),
    closeMin: hm(21, 0),
    preMin: 30,
  },
];

// ---------------------------------------------------------------------------
// Compute market state from current IST time
// ---------------------------------------------------------------------------

function istMinutes(now: Date): number {
  // Convert to IST (UTC+5:30)
  const utcMs = now.getTime() + now.getTimezoneOffset() * 60_000;
  const istMs = utcMs + 5.5 * 3_600_000;
  const istDate = new Date(istMs);
  return istDate.getHours() * 60 + istDate.getMinutes() + istDate.getSeconds() / 60;
}

function computeMarketState(def: MarketDef, nowMin: number, nowMs: number): MarketState {
  const { openMin, closeMin, preMin } = def;

  // Normalise: wrap close past midnight
  const isOpen = nowMin >= openMin && nowMin < closeMin;
  const isPre = !isOpen && nowMin >= openMin - preMin && nowMin < openMin;
  const status: MarketStatus = isOpen ? "open" : isPre ? "pre" : "closed";

  let progress = 0;
  let remainingMs = 0;

  if (isOpen) {
    const sessionLen = closeMin - openMin;
    progress = (nowMin - openMin) / sessionLen;
    remainingMs = (closeMin - nowMin) * 60_000 - (nowMs % 1000);
  } else if (isPre) {
    progress = 0;
    remainingMs = (openMin - nowMin) * 60_000 - (nowMs % 1000);
  } else {
    progress = 0;
    // Time until next open (could be tomorrow)
    let minsUntil = openMin - nowMin;
    if (minsUntil < 0) minsUntil += 1440;
    remainingMs = minsUntil * 60_000;
  }

  return { def, status, progress: Math.min(1, Math.max(0, progress)), remainingMs };
}

// ---------------------------------------------------------------------------
// Formatting helpers
// ---------------------------------------------------------------------------

function fmtDuration(ms: number): string {
  const totalSec = Math.max(0, Math.floor(ms / 1000));
  const h = Math.floor(totalSec / 3600);
  const m = Math.floor((totalSec % 3600) / 60);
  const s = totalSec % 60;
  if (h > 0) return `${h}h ${String(m).padStart(2, "0")}m`;
  if (m > 0) return `${m}m ${String(s).padStart(2, "0")}s`;
  return `${s}s`;
}

function fmtTime(min: number): string {
  const h = Math.floor(min % 1440 / 60);
  const m = min % 60;
  return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}`;
}

// ---------------------------------------------------------------------------
// Status badge
// ---------------------------------------------------------------------------

const STATUS_LABEL: Record<MarketStatus, string> = {
  open: "Open",
  pre: "Pre-market",
  closed: "Closed",
};

const STATUS_CLASS: Record<MarketStatus, string> = {
  open: "text-profit bg-profit/10 border-profit/30",
  pre: "text-warning bg-warning/10 border-warning/30",
  closed: "text-text-muted bg-surface-hover border-border-default",
};

const BAR_CLASS: Record<MarketStatus, string> = {
  open: "bg-profit",
  pre: "bg-warning",
  closed: "bg-surface-hover",
};

// ---------------------------------------------------------------------------
// Single market row
// ---------------------------------------------------------------------------

interface MarketRowProps {
  state: MarketState;
}

function MarketRow({ state }: MarketRowProps) {
  const { def, status, progress, remainingMs } = state;
  const isOpen = status === "open";
  const isPre = status === "pre";

  return (
    <div
      className="px-3 py-2.5 border-b border-border-default last:border-0"
      role="listitem"
      aria-label={`${def.name} market status: ${STATUS_LABEL[status]}`}
    >
      <div className="flex items-center gap-2 mb-1.5">
        {/* Name + description */}
        <div className="flex-1 min-w-0">
          <div className="text-xs font-semibold text-text-primary leading-tight">{def.name}</div>
          <div className="text-xxs text-text-muted">{def.description}</div>
        </div>

        {/* Status badge */}
        <span
          className={cn(
            "px-1.5 py-0.5 text-xxs font-medium border rounded shrink-0",
            STATUS_CLASS[status],
          )}
        >
          {STATUS_LABEL[status]}
        </span>

        {/* Time remaining / opens in */}
        <div className="text-right shrink-0 min-w-14">
          <div
            className={cn(
              "text-xs font-mono tabular-nums font-semibold",
              isOpen ? "text-profit" : isPre ? "text-warning" : "text-text-muted",
            )}
            aria-live="polite"
            aria-atomic="true"
          >
            {fmtDuration(remainingMs)}
          </div>
          <div className="text-xxs text-text-muted">
            {isOpen ? "closes" : isPre ? "opens" : "opens"}
          </div>
        </div>
      </div>

      {/* Progress bar */}
      <div
        className="h-1 rounded-full overflow-hidden bg-surface-base"
        role="progressbar"
        aria-valuenow={Math.round(progress * 100)}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label={`${def.name} session progress`}
      >
        <div
          className={cn("h-full rounded-full transition-[width]", BAR_CLASS[status])}
          style={{ width: `${progress * 100}%` }}
        />
      </div>

      {/* Open / close times */}
      <div className="flex justify-between mt-1 text-xxs text-text-muted">
        <span>{fmtTime(def.openMin)} IST</span>
        <span>{fmtTime(def.closeMin)} IST</span>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main widget
// ---------------------------------------------------------------------------

function MarketClockWidget() {
  const track = useTrackBehavior();
  const [now, setNow] = useState(() => new Date());

  useEffect(() => {
    track("trade", "widget_view_market_clock");
    const id = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(id);
  }, [track]);

  const states = useMemo<MarketState[]>(() => {
    const curMin = istMinutes(now);
    const nowMs = now.getTime();
    return MARKET_DEFS.map((def) => computeMarketState(def, curMin, nowMs));
  }, [now]);

  const openCount = states.filter((s) => s.status === "open").length;

  return (
    <div
      className="h-full flex flex-col bg-surface-base overflow-hidden"
      aria-label="Market Clock widget"
    >
      {/* Header */}
      <div className="flex-none flex items-center gap-2 px-2 py-1.5 bg-surface-card border-b border-border-default">
        <Clock size={13} className="text-accent shrink-0" aria-hidden="true" />
        <span className="text-xs font-semibold text-text-primary">Market Clock</span>
        <div className="flex-1" />
        <span className="text-xxs text-text-muted tabular-nums">
          {now.toLocaleTimeString("en-IN", { timeZone: "Asia/Kolkata", hour12: false })} IST
        </span>
        {openCount > 0 && (
          <span className="px-1.5 py-0.5 text-xxs bg-profit/10 text-profit border border-profit/30 rounded">
            {openCount} open
          </span>
        )}
      </div>

      {/* Market rows */}
      <div
        className="flex-1 min-h-0 overflow-y-auto"
        role="list"
        aria-label="Market session list"
      >
        {states.map((state) => (
          <MarketRow key={state.def.name} state={state} />
        ))}
      </div>

      {/* Legend */}
      <div className="flex-none px-3 py-2 border-t border-border-default">
        <div className="flex items-center gap-3 text-xxs text-text-muted">
          <span className="flex items-center gap-1">
            <span className="w-2 h-2 rounded-full bg-profit inline-block" />
            Open
          </span>
          <span className="flex items-center gap-1">
            <span className="w-2 h-2 rounded-full bg-warning inline-block" />
            Pre-market
          </span>
          <span className="flex items-center gap-1">
            <span className="w-2 h-2 rounded-full bg-surface-hover border border-border-default inline-block" />
            Closed
          </span>
          <span className="ml-auto text-text-muted">All times IST</span>
        </div>
      </div>
    </div>
  );
}

export default memo(MarketClockWidget);
