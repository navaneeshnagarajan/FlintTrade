/**
 * StrategyMonitorWidget — Live status of running algorithmic strategies.
 *
 * Features:
 *   - One row per strategy: name, status, symbol, P&L, trade count, signal count
 *   - Status: Running (green) / Paused (amber) / Stopped (grey) / Error (red)
 *   - Per-strategy Start / Pause / Stop action buttons
 *   - Overall health indicator in header (all OK / degraded / critical)
 *   - Log viewer: last 5 log messages per strategy (expandable)
 *   - Sample data when broker disconnected
 */

import { useState, useCallback, useEffect, memo } from "react";
import { Activity, Play, Pause, Square, ChevronDown, ChevronRight, AlertTriangle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useTrackBehavior } from "@/hooks/useTrackBehavior";
import { useBrokerConnected } from "@/hooks/useBrokerConnected";
import { cn } from "@/lib/utils";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type StrategyStatus = "running" | "paused" | "stopped" | "error";

export interface StrategyLogEntry {
  ts: string;
  level: "info" | "warn" | "error";
  message: string;
}

export interface Strategy {
  id: string;
  name: string;
  status: StrategyStatus;
  symbol: string;
  pnl: number;
  tradesToday: number;
  signalsGenerated: number;
  logs: StrategyLogEntry[];
}

type OverallHealth = "ok" | "degraded" | "critical";

// ---------------------------------------------------------------------------
// Sample data
// ---------------------------------------------------------------------------

export const SAMPLE_STRATEGIES: Strategy[] = [
  {
    id: "s1",
    name: "NIFTY Iron Condor",
    status: "running",
    symbol: "NIFTY",
    pnl: 4320,
    tradesToday: 2,
    signalsGenerated: 5,
    logs: [
      { ts: "10:14:02", level: "info",  message: "Short strangle placed @ 22400" },
      { ts: "10:14:01", level: "info",  message: "Signal: enter iron condor (IV rank 68)" },
      { ts: "09:45:11", level: "info",  message: "Strategy started" },
      { ts: "09:45:10", level: "info",  message: "Parameters loaded: width=200, delta=0.15" },
      { ts: "09:15:00", level: "info",  message: "Market open — scanning" },
    ],
  },
  {
    id: "s2",
    name: "BANKNIFTY Scalper",
    status: "paused",
    symbol: "BANKNIFTY",
    pnl: -620,
    tradesToday: 7,
    signalsGenerated: 14,
    logs: [
      { ts: "11:02:55", level: "warn",  message: "Paused: daily loss limit 50% reached" },
      { ts: "10:58:01", level: "error", message: "Slippage 1.2 pts on BANKNIFTY FUT — threshold exceeded" },
      { ts: "10:55:30", level: "info",  message: "Long 1 lot @ 48420" },
      { ts: "10:54:12", level: "info",  message: "Signal: momentum long (RSI 34)" },
      { ts: "10:30:00", level: "info",  message: "First trade of session" },
    ],
  },
  {
    id: "s3",
    name: "Options Theta Harvester",
    status: "running",
    symbol: "FINNIFTY",
    pnl: 1890,
    tradesToday: 1,
    signalsGenerated: 3,
    logs: [
      { ts: "10:00:05", level: "info",  message: "Calendar spread entered (near vs far)" },
      { ts: "09:55:50", level: "info",  message: "IV spread 2.4% — signal fired" },
      { ts: "09:15:30", level: "info",  message: "Strategy started" },
      { ts: "09:15:00", level: "info",  message: "Loading expiry chain" },
      { ts: "09:14:55", level: "info",  message: "Subscribed to FINNIFTY options feed" },
    ],
  },
  {
    id: "s4",
    name: "MCX Gold Trend",
    status: "error",
    symbol: "GOLD",
    pnl: 0,
    tradesToday: 0,
    signalsGenerated: 0,
    logs: [
      { ts: "09:01:33", level: "error", message: "Connection to MCX feed failed" },
      { ts: "09:01:32", level: "error", message: "Symbol GOLD not found on exchange MCX" },
      { ts: "09:01:30", level: "warn",  message: "Retrying symbol lookup..." },
      { ts: "09:01:10", level: "info",  message: "Initialising MCX Gold Trend strategy" },
      { ts: "09:01:00", level: "info",  message: "Strategy scheduled to start at 09:01" },
    ],
  },
];

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function computeHealth(strategies: Strategy[]): OverallHealth {
  const errorCount = strategies.filter((s) => s.status === "error").length;
  if (errorCount > 0) return "critical";
  const pausedCount = strategies.filter((s) => s.status === "paused").length;
  if (pausedCount > 0) return "degraded";
  return "ok";
}

function fmtPnl(v: number): string {
  const sign = v >= 0 ? "+" : "−";
  return `${sign}₹${Math.abs(v).toLocaleString("en-IN")}`;
}

// ---------------------------------------------------------------------------
// Status badge
// ---------------------------------------------------------------------------

const STATUS_LABEL: Record<StrategyStatus, string> = {
  running: "Running",
  paused:  "Paused",
  stopped: "Stopped",
  error:   "Error",
};

const STATUS_CLASS: Record<StrategyStatus, string> = {
  running: "text-profit bg-profit/10 border-profit/30",
  paused:  "text-warning bg-warning/10 border-warning/30",
  stopped: "text-text-muted bg-surface-hover border-border-default",
  error:   "text-loss bg-loss/10 border-loss/30",
};

const LOG_COLOUR: Record<StrategyLogEntry["level"], string> = {
  info:  "text-text-muted",
  warn:  "text-warning",
  error: "text-loss",
};

// ---------------------------------------------------------------------------
// Strategy row
// ---------------------------------------------------------------------------

interface StrategyRowProps {
  strategy: Strategy;
  onStart: (id: string) => void;
  onPause: (id: string) => void;
  onStop:  (id: string) => void;
}

function StrategyRow({ strategy, onStart, onPause, onStop }: StrategyRowProps) {
  const [logsOpen, setLogsOpen] = useState(false);
  const { id, name, status, symbol, pnl, tradesToday, signalsGenerated, logs } = strategy;

  return (
    <div
      className="border-b border-border-default last:border-0"
      role="listitem"
      aria-label={`Strategy ${name}: ${STATUS_LABEL[status]}`}
    >
      {/* Main row */}
      <div className="flex items-center gap-2 px-3 py-2.5">
        {/* Expand toggle */}
        <Button
          variant="ghost"
          size="icon"
          onClick={() => setLogsOpen((o) => !o)}
          className="h-auto w-auto p-0 text-text-muted hover:text-text-primary transition-colors shrink-0"
          aria-label={logsOpen ? `Collapse logs for ${name}` : `Expand logs for ${name}`}
          aria-expanded={logsOpen}
        >
          {logsOpen
            ? <ChevronDown size={12} />
            : <ChevronRight size={12} />
          }
        </Button>

        {/* Name + symbol */}
        <div className="flex-1 min-w-0">
          <div className="text-xs font-semibold text-text-primary truncate" title={name}>{name}</div>
          <div className="text-xxs text-text-muted">{symbol}</div>
        </div>

        {/* Status badge */}
        <span className={cn("px-1.5 py-0.5 text-xxs font-medium border rounded shrink-0", STATUS_CLASS[status])}>
          {STATUS_LABEL[status]}
        </span>

        {/* P&L */}
        <span
          className={cn(
            "text-xs font-mono tabular-nums font-semibold shrink-0 min-w-16 text-right",
            pnl >= 0 ? "text-profit" : "text-loss",
          )}
        >
          {fmtPnl(pnl)}
        </span>

        {/* Counts */}
        <div className="text-xxs text-text-muted shrink-0 min-w-12 text-right">
          <div>{tradesToday}T</div>
          <div>{signalsGenerated}S</div>
        </div>

        {/* Action buttons */}
        <div className="flex items-center gap-1 shrink-0" role="group" aria-label={`Actions for ${name}`}>
          <Button
            variant="ghost"
            size="icon"
            onClick={() => onStart(id)}
            disabled={status === "running"}
            className="h-auto w-auto p-1 text-text-muted hover:text-profit hover:bg-profit/10 transition-colors disabled:opacity-30"
            title="Start"
            aria-label={`Start ${name}`}
          >
            <Play size={11} />
          </Button>
          <Button
            variant="ghost"
            size="icon"
            onClick={() => onPause(id)}
            disabled={status !== "running"}
            className="h-auto w-auto p-1 text-text-muted hover:text-warning hover:bg-warning/10 transition-colors disabled:opacity-30"
            title="Pause"
            aria-label={`Pause ${name}`}
          >
            <Pause size={11} />
          </Button>
          <Button
            variant="ghost"
            size="icon"
            onClick={() => onStop(id)}
            disabled={status === "stopped"}
            className="h-auto w-auto p-1 text-text-muted hover:text-loss hover:bg-loss/10 transition-colors disabled:opacity-30"
            title="Stop"
            aria-label={`Stop ${name}`}
          >
            <Square size={11} />
          </Button>
        </div>
      </div>

      {/* Log drawer */}
      {logsOpen && (
        <div
          className="mx-3 mb-2 rounded bg-surface-base border border-border-subtle overflow-hidden"
          aria-label={`Logs for ${name}`}
        >
          {logs.slice(0, 5).map((entry, i) => (
            <div
              key={i}
              className="flex items-start gap-2 px-2 py-1 border-b border-border-subtle last:border-0"
            >
              <span className="text-xxs text-text-muted font-mono shrink-0">{entry.ts}</span>
              <span className={cn("text-xxs font-mono flex-1", LOG_COLOUR[entry.level])}>
                {entry.message}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Overall health badge
// ---------------------------------------------------------------------------

const HEALTH_CLASS: Record<OverallHealth, string> = {
  ok:       "text-profit bg-profit/10 border-profit/30",
  degraded: "text-warning bg-warning/10 border-warning/30",
  critical: "text-loss bg-loss/10 border-loss/30",
};

const HEALTH_LABEL: Record<OverallHealth, string> = {
  ok:       "All OK",
  degraded: "Degraded",
  critical: "Critical",
};

// ---------------------------------------------------------------------------
// Main widget
// ---------------------------------------------------------------------------

function StrategyMonitorWidget() {
  const track = useTrackBehavior();
  const isConnected = useBrokerConnected();
  const [strategies, setStrategies] = useState<Strategy[]>(() =>
    isConnected ? [] : SAMPLE_STRATEGIES,
  );

  useEffect(() => {
    track("trade", "widget_view_strategy_monitor");
  }, [track]);

  // House rule: never render fabricated live P&L. Demo strategies show only when
  // no broker is connected (explore/demo, with the "Sample" badge). When a broker
  // IS connected we show the honest "No strategies configured" empty state rather
  // than sample data presented as live — real strategy monitoring is wired via
  // Automate -> Strategies (the StrategyRunner) until this widget subscribes to it.
  useEffect(() => {
    setStrategies(isConnected ? [] : SAMPLE_STRATEGIES);
  }, [isConnected]);

  const health = computeHealth(strategies);

  const handleStart = useCallback((id: string) => {
    setStrategies((prev) =>
      prev.map((s) => s.id === id ? { ...s, status: "running" as StrategyStatus } : s),
    );
  }, []);

  const handlePause = useCallback((id: string) => {
    setStrategies((prev) =>
      prev.map((s) => s.id === id ? { ...s, status: "paused" as StrategyStatus } : s),
    );
  }, []);

  const handleStop = useCallback((id: string) => {
    setStrategies((prev) =>
      prev.map((s) => s.id === id ? { ...s, status: "stopped" as StrategyStatus } : s),
    );
  }, []);

  const runningCount = strategies.filter((s) => s.status === "running").length;

  return (
    <div
      className="h-full flex flex-col bg-surface-base overflow-hidden"
      aria-label="Strategy Monitor widget"
    >
      {/* Header */}
      <div className="flex-none flex items-center gap-2 px-2 py-1.5 bg-surface-card border-b border-border-default flex-wrap">
        <Activity size={13} className="text-accent shrink-0" aria-hidden="true" />
        <span className="text-xs font-semibold text-text-primary">Strategy Monitor</span>

        <span
          className={cn("px-1.5 py-0.5 text-xxs font-medium border rounded", HEALTH_CLASS[health])}
          aria-label={`Overall health: ${HEALTH_LABEL[health]}`}
        >
          {health === "critical" && <AlertTriangle size={9} className="inline mr-0.5" />}
          {HEALTH_LABEL[health]}
        </span>

        <div className="flex-1" />

        <span className="text-xxs text-text-muted">{runningCount} running</span>

        {!isConnected && (
          <span className="px-1.5 py-0.5 text-xxs bg-warning/10 text-warning border border-warning/30 rounded">
            Sample
          </span>
        )}
      </div>

      {/* Column headers */}
      <div className="flex-none flex items-center gap-2 px-3 py-1 bg-surface-card border-b border-border-subtle text-xxs text-text-muted">
        <div className="w-4 shrink-0" />
        <div className="flex-1">Name / Symbol</div>
        <div className="w-16 shrink-0 text-right">Status</div>
        <div className="w-16 shrink-0 text-right">P&amp;L</div>
        <div className="w-12 shrink-0 text-right">T / S</div>
        <div className="w-20 shrink-0 text-right">Actions</div>
      </div>

      {/* Strategy rows */}
      <div
        className="flex-1 min-h-0 overflow-y-auto"
        role="list"
        aria-label="Strategy list"
      >
        {strategies.length === 0 ? (
          <div className="flex flex-col items-center justify-center gap-2 h-full px-4 text-center">
            <p className="text-sm text-text-muted">No strategies configured</p>
            <p className="text-xxs text-text-muted leading-snug">
              Build and deploy a strategy in the Strategy Lab to monitor it here.
            </p>
            <Button
              variant="outline"
              size="sm"
              className="mt-1"
              onClick={() =>
                window.dispatchEvent(
                  new CustomEvent("flinttrade:navigate", { detail: "/lab" }),
                )
              }
            >
              Open Strategy Lab
            </Button>
          </div>
        ) : (
          strategies.map((s) => (
            <StrategyRow
              key={s.id}
              strategy={s}
              onStart={handleStart}
              onPause={handlePause}
              onStop={handleStop}
            />
          ))
        )}
      </div>

      {/* Footer summary */}
      <div className="flex-none px-3 py-2 border-t border-border-default">
        <div className="flex items-center gap-4 text-xxs text-text-muted">
          <span>
            Total P&amp;L:&nbsp;
            <span
              className={cn(
                "font-mono font-semibold",
                strategies.reduce((s, x) => s + x.pnl, 0) >= 0 ? "text-profit" : "text-loss",
              )}
            >
              {fmtPnl(strategies.reduce((s, x) => s + x.pnl, 0))}
            </span>
          </span>
          <span>
            Trades:&nbsp;
            <span className="text-text-primary font-semibold">
              {strategies.reduce((s, x) => s + x.tradesToday, 0)}
            </span>
          </span>
          <span>
            Signals:&nbsp;
            <span className="text-text-primary font-semibold">
              {strategies.reduce((s, x) => s + x.signalsGenerated, 0)}
            </span>
          </span>
        </div>
      </div>
    </div>
  );
}

export default memo(StrategyMonitorWidget);
