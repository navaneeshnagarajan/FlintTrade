/**
 * usePineRunner.ts
 *
 * React hook that fetches OHLCV history from OpenAlgo and runs the Pine Script
 * executor against those bars. Follows FlintTrade state architecture:
 *   - getHistory() → REST API (TanStack Query is not used here since this is a
 *     one-shot imperative run, not a cached subscription)
 *   - No Jotai/Zustand state — all result state is local to the Strategy Builder
 *
 * Date range defaults: last 365 calendar days → today (IST).
 * The caller may override start/end dates for custom backtesting windows.
 */

import { useState, useCallback } from "react";
import { getHistory } from "@/services/api";
import { executePineScript } from "./pineExecutor";
import type { PineResult, BarData } from "./pineExecutor";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface PineRunnerOptions {
  /** ISO date string "YYYY-MM-DD". Defaults to 365 days ago. */
  startDate?: string;
  /** ISO date string "YYYY-MM-DD". Defaults to today. */
  endDate?: string;
}

export interface PineRunnerState {
  result: PineResult | null;
  /** Raw bars used for execution — exposed so the chart can plot them */
  bars: BarData[];
  isRunning: boolean;
  error: string | null;
}

export interface PineRunnerActions {
  /**
   * Fetch bars for the given symbol/exchange/interval and execute the Pine
   * Script code against them.
   */
  run: (
    code: string,
    symbol: string,
    exchange: string,
    interval: string,
    opts?: PineRunnerOptions,
  ) => Promise<void>;
  /** Reset all state back to initial */
  reset: () => void;
}

export type UsePineRunnerReturn = PineRunnerState & PineRunnerActions;

// ---------------------------------------------------------------------------
// Date helpers (IST-safe, no external deps)
// ---------------------------------------------------------------------------

/** Format a Date to "YYYY-MM-DD" in local timezone. */
function toLocalDateString(date: Date): string {
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, "0");
  const d = String(date.getDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
}

/** Return today and (today - offsetDays) as "YYYY-MM-DD" strings. */
function defaultDateRange(offsetDays: number): { start: string; end: string } {
  const now = new Date();
  const end = toLocalDateString(now);
  const past = new Date(now);
  past.setDate(past.getDate() - offsetDays);
  const start = toLocalDateString(past);
  return { start, end };
}

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

const INITIAL_STATE: PineRunnerState = {
  result: null,
  bars: [],
  isRunning: false,
  error: null,
};

export function usePineRunner(): UsePineRunnerReturn {
  const [state, setState] = useState<PineRunnerState>(INITIAL_STATE);

  const run = useCallback(
    async (
      code: string,
      symbol: string,
      exchange: string,
      interval: string,
      opts?: PineRunnerOptions,
    ) => {
      if (!code.trim()) {
        setState((prev) => ({ ...prev, error: "Pine Script code is empty." }));
        return;
      }
      if (!symbol.trim() || !exchange.trim()) {
        setState((prev) => ({
          ...prev,
          error: "Symbol and exchange are required to fetch historical data.",
        }));
        return;
      }

      setState((prev) => ({ ...prev, isRunning: true, error: null, result: null, bars: [] }));

      try {
        const { start, end } = defaultDateRange(365);
        const startDate = opts?.startDate ?? start;
        const endDate = opts?.endDate ?? end;

        // OpenAlgo history endpoint — OHLCVBar[] from api.ts
        const rawBars = await getHistory(symbol, exchange, interval, startDate, endDate);

        if (!Array.isArray(rawBars) || rawBars.length === 0) {
          setState((prev) => ({
            ...prev,
            isRunning: false,
            error: `No bar data returned for ${symbol} (${exchange}) on interval "${interval}". Check symbol, exchange, and date range.`,
          }));
          return;
        }

        // OHLCVBar uses `timestamp` — BarData uses `time` (same semantics, just renamed)
        const bars: BarData[] = rawBars.map((b) => ({
          time: b.timestamp,
          open: b.open,
          high: b.high,
          low: b.low,
          close: b.close,
          volume: b.volume,
        }));

        const result = executePineScript(code, bars);

        setState({
          result,
          bars,
          isRunning: false,
          error: result.errors.length > 0 ? null : null, // errors surfaced via result.errors, not top-level error
        });
      } catch (e) {
        setState({
          result: null,
          bars: [],
          isRunning: false,
          error: e instanceof Error ? e.message : "Execution failed — unknown error.",
        });
      }
    },
    [],
  );

  const reset = useCallback(() => {
    setState(INITIAL_STATE);
  }, []);

  return { ...state, run, reset };
}
