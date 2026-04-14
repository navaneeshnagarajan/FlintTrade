/**
 * TanStack Query hooks for the live signal pipeline (v0.5.0).
 *
 * - useRecentSignals()  — polls GET /api/v1/signals/recent every 5 s
 * - useSignalConfig()   — fetches GET /api/v1/signals/config (stale 60 s)
 * - useSignalStream()   — SSE EventSource for real-time signals
 * - useUpdateSignalConfig() — mutation for POST /api/v1/signals/configure
 *
 * Mode-aware: in "explore" mode, returns sample signals without hitting the
 * backend so the UI works without a running Python server.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { z } from "zod";
import { safeParse } from "@/lib/safeParse";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  getRecentSignals,
  getSignalConfig,
  updateSignalConfig,
} from "@/services/ftApi";
import type { LiveSignal, SignalConfig } from "@/services/ftApi";
import { useModeStore } from "@/stores/modeStore";
import { isMarketHours } from "@/lib/market";

// ---------------------------------------------------------------------------
// Sample data for explore mode
// ---------------------------------------------------------------------------

const SAMPLE_SIGNALS: LiveSignal[] = [
  {
    timestamp: new Date().toISOString(),
    symbol: "NIFTY",
    signal_type: "BUY",
    indicator: "RSI",
    value: 28.5,
    threshold: 30,
    confidence: 0.72,
    message: "NIFTY RSI(14) = 28.5 below oversold threshold 30",
  },
  {
    timestamp: new Date(Date.now() - 60_000).toISOString(),
    symbol: "BANKNIFTY",
    signal_type: "SELL",
    indicator: "EMA_Cross",
    value: -45.2,
    threshold: 0,
    confidence: 0.65,
    message: "BANKNIFTY EMA(9) crossed below EMA(21)",
  },
  {
    timestamp: new Date(Date.now() - 120_000).toISOString(),
    symbol: "NIFTY",
    signal_type: "BUY",
    indicator: "MACD",
    value: 12.3,
    threshold: 0,
    confidence: 0.60,
    message: "NIFTY MACD histogram turned positive (12.30)",
  },
];

const SAMPLE_CONFIG: SignalConfig = {
  instruments: ["NIFTY", "BANKNIFTY"],
  indicators: [
    { name: "RSI", params: { period: 14 } },
    { name: "EMA_Cross", params: { fast: 9, slow: 21 } },
    { name: "MACD", params: { fast: 12, slow: 26, signal: 9 } },
  ],
  thresholds: {
    rsi_oversold: 30,
    rsi_overbought: 70,
    macd_crossover_min: 0,
    ema_cross_min_pct: 0,
  },
};

// ---------------------------------------------------------------------------
// useRecentSignals — polls recent signals every 5 seconds
// ---------------------------------------------------------------------------

export function useRecentSignals(limit = 20) {
  const mode = useModeStore((s) => s.mode);

  return useQuery<{ signals: LiveSignal[] }>({
    queryKey: ["signals", "recent", limit],
    queryFn: () => {
      if (mode === "explore") {
        return Promise.resolve({ signals: SAMPLE_SIGNALS });
      }
      return getRecentSignals(limit);
    },
    staleTime: 5_000,
    refetchInterval: () => (isMarketHours() ? 5_000 : false),
    retry: false,
  });
}

// ---------------------------------------------------------------------------
// useSignalConfig — current pipeline configuration
// ---------------------------------------------------------------------------

export function useSignalConfig() {
  const mode = useModeStore((s) => s.mode);

  return useQuery<SignalConfig>({
    queryKey: ["signals", "config"],
    queryFn: () => {
      if (mode === "explore") {
        return Promise.resolve(SAMPLE_CONFIG);
      }
      return getSignalConfig();
    },
    staleTime: 60_000,
    retry: false,
  });
}

// ---------------------------------------------------------------------------
// useUpdateSignalConfig — mutation to update configuration
// ---------------------------------------------------------------------------

export function useUpdateSignalConfig() {
  const qc = useQueryClient();

  return useMutation<SignalConfig, Error, Partial<SignalConfig>>({
    mutationFn: updateSignalConfig,
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["signals", "config"] });
      void qc.invalidateQueries({ queryKey: ["signals", "recent"] });
    },
  });
}

// ---------------------------------------------------------------------------
// useSignalStream — SSE EventSource for real-time signal events
// ---------------------------------------------------------------------------

export function useSignalStream(
  onSignal: (signal: LiveSignal) => void,
  enabled = true,
) {
  const mode = useModeStore((s) => s.mode);
  const esRef = useRef<EventSource | null>(null);
  const [connected, setConnected] = useState(false);
  const callbackRef = useRef(onSignal);
  callbackRef.current = onSignal;

  const connect = useCallback(() => {
    if (mode === "explore" || !enabled) return;

    const base = import.meta.env.DEV ? "/ft-api" : "";
    const url = `${base}/api/v1/signals/stream`;
    const es = new EventSource(url);

    es.onopen = () => setConnected(true);
    es.onerror = () => {
      setConnected(false);
      // EventSource auto-reconnects — no manual reconnect needed
    };
    const liveSignalSchema = z.object({
      timestamp: z.string(),
      symbol: z.string(),
      signal_type: z.enum(["BUY", "SELL", "ALERT"]),
      indicator: z.string(),
      value: z.number(),
      threshold: z.number(),
      confidence: z.number(),
      message: z.string(),
    }) satisfies z.ZodType<LiveSignal>;

    es.onmessage = (event) => {
      const signal = safeParse(event.data as string, liveSignalSchema);
      if (signal) callbackRef.current(signal);
      // Malformed frames and heartbeat comments are silently discarded
    };

    esRef.current = es;
  }, [mode, enabled]);

  useEffect(() => {
    connect();
    return () => {
      esRef.current?.close();
      esRef.current = null;
      setConnected(false);
    };
  }, [connect]);

  return { connected };
}
