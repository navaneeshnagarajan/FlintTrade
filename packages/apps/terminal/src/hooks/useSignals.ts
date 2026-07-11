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
import { buildHeaders, getBase } from "@/services/ftApi.helpers";
import { safeParse } from "@/lib/safeParse";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  getRecentSignals,
  getSignalConfig,
  updateSignalConfig,
} from "@/services/ftApi";
import { signalEventSchema } from "@/services/ftApi.ai";
import type { SignalConfig, SignalEvent } from "@/services/ftApi";
import { useModeStore } from "@/stores/modeStore";
import { useAuthStore } from "@/stores/authStore";
import { useConnectionStore } from "@/stores/connectionStore";
import { useHolidays } from "@/hooks/useMarketStatus";
import { isMarketHours } from "@/lib/market";
import type { MarketHoursInstrument } from "@/lib/market";
import type { Holiday } from "@/types/api";

// ---------------------------------------------------------------------------
// Sample data for explore mode
// ---------------------------------------------------------------------------

export { signalEventSchema };

const SAMPLE_SIGNALS: SignalEvent[] = [
  {
    event_id: 3,
    timestamp: new Date().toISOString(),
    symbol: "NIFTY",
    exchange: "NSE_INDEX",
    signal_type: "BUY",
    source: "rule",
    method: "RSI",
    indicator: "RSI",
    value: 28.5,
    threshold: 30,
    confidence: 0.72,
    message: "NIFTY RSI(14) = 28.5 below oversold threshold 30",
    metadata: {},
  },
  {
    event_id: 2,
    timestamp: new Date(Date.now() - 60_000).toISOString(),
    symbol: "BANKNIFTY",
    exchange: "NSE_INDEX",
    signal_type: "SELL",
    source: "ml",
    method: "ml_model",
    indicator: "LightGBM",
    value: 51_420,
    threshold: 0,
    confidence: 0.74,
    message: "BANKNIFTY scheduled ML model signal: SELL",
    metadata: { turbulence_score: 0.18 },
  },
  {
    event_id: 1,
    timestamp: new Date(Date.now() - 120_000).toISOString(),
    symbol: "NIFTY",
    exchange: "NSE_INDEX",
    signal_type: "BUY",
    source: "fallback",
    method: "ema_crossover_fallback",
    indicator: "EMA_Cross",
    value: 24_240,
    threshold: 0,
    confidence: 0.55,
    message: "NIFTY scheduled EMA crossover fallback signal: BUY",
    metadata: {},
  },
];

const SAMPLE_CONFIG: SignalConfig = {
  instruments: ["NSE_INDEX:NIFTY", "NSE_INDEX:BANKNIFTY"],
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

function parseConfiguredInstrument(identity: string): MarketHoursInstrument | undefined {
  const parts = identity.split(":");
  if (parts.length !== 2 || !parts[0] || !parts[1]) return undefined;
  return { exchange: parts[0], symbol: parts[1] };
}

function signalIdentity(signal: SignalEvent): string {
  if (signal.event_id > 0 && signal.stream_id) {
    return `event:${signal.stream_id}:${signal.event_id}`;
  }
  if (signal.event_id > 0) return `event:legacy:${signal.event_id}`;
  return `legacy:${signal.timestamp}:${signal.exchange}:${signal.symbol}:${signal.method}`;
}

function signalTimestamp(signal: SignalEvent): number {
  const timestamp = Date.parse(signal.timestamp);
  return Number.isFinite(timestamp) ? timestamp : Number.NEGATIVE_INFINITY;
}

function compareSignalRecency(left: SignalEvent, right: SignalEvent): number {
  const sameQualifiedStream = Boolean(
    left.stream_id
    && right.stream_id
    && left.stream_id === right.stream_id,
  );
  if (sameQualifiedStream) {
    return right.event_id - left.event_id
      || signalTimestamp(right) - signalTimestamp(left);
  }

  const timestampDelta = signalTimestamp(right) - signalTimestamp(left);
  if (timestampDelta !== 0) return timestampDelta;

  // Numeric IDs remain comparable for legacy payloads from one unqualified
  // process, but never take precedence across known process identities.
  if (!left.stream_id && !right.stream_id) return right.event_id - left.event_id;
  return 0;
}

/** Merge signal snapshots without allowing an older source to evict newer events. */
export function reconcileSignalEvents(
  preferred: readonly SignalEvent[],
  fallback: readonly SignalEvent[],
  limit: number,
): SignalEvent[] {
  const byIdentity = new Map<string, SignalEvent>();
  for (const signal of fallback) byIdentity.set(signalIdentity(signal), signal);
  for (const signal of preferred) byIdentity.set(signalIdentity(signal), signal);

  return [...byIdentity.values()]
    .sort(compareSignalRecency)
    .slice(0, limit);
}

function isAnyConfiguredMarketOpen(
  instruments: string[],
  holidays?: readonly Holiday[],
): boolean {
  return instruments.some((identity) => {
    const instrument = parseConfiguredInstrument(identity);
    return instrument ? isMarketHours(instrument, holidays) : false;
  });
}

export function useRecentSignals(limit = 20) {
  const mode = useModeStore((s) => s.mode);
  const configQuery = useSignalConfig();
  const holidayQuery = useHolidays(mode !== "explore");
  const qc = useQueryClient();
  const queryKey = ["signals", "recent", mode, limit] as const;

  return useQuery<{ signals: SignalEvent[] }>({
    queryKey,
    queryFn: async () => {
      const incoming = mode === "explore"
        ? { signals: SAMPLE_SIGNALS }
        : await getRecentSignals(limit);
      const cached = qc.getQueryData<{ signals: SignalEvent[] }>(queryKey);
      return {
        signals: reconcileSignalEvents(
          cached?.signals ?? [],
          incoming.signals,
          limit,
        ),
      };
    },
    staleTime: 5_000,
    refetchOnMount: "always",
    refetchInterval: () => {
      if (configQuery.isPending) return 5_000;
      if (mode !== "explore" && holidayQuery.isPending) return 60_000;
      const isOpen = configQuery.data
        ? isAnyConfiguredMarketOpen(configQuery.data.instruments, holidayQuery.data)
        : isMarketHours(undefined, holidayQuery.data);
      return isOpen ? 5_000 : 60_000;
    },
    retry: false,
  });
}

// ---------------------------------------------------------------------------
// useSignalConfig — current pipeline configuration
// ---------------------------------------------------------------------------

export function useSignalConfig() {
  const mode = useModeStore((s) => s.mode);

  return useQuery<SignalConfig>({
    queryKey: ["signals", "config", mode],
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
// useSignalStream — authenticated fetch/ReadableStream SSE client
// ---------------------------------------------------------------------------

export const signalReplayLossSchema = z.object({
  reason: z.string().min(1),
  requested_event_id: z.union([z.number().int(), z.string().min(1)]),
  oldest_available_event_id: z.union([z.number().int(), z.string().min(1)]).nullable(),
  newest_available_event_id: z.union([z.number().int(), z.string().min(1)]),
});

export type SignalReplayLoss = z.infer<typeof signalReplayLossSchema>;

interface ParsedSseEvent {
  type: string;
  data: string;
  id?: string;
}

const SIGNAL_STREAM_CURSOR_KEY = "flinttrade:signals:sse-cursor:v1";
const STREAM_RETRY_BASE_MS = 1_000;
const STREAM_RETRY_MAX_MS = 30_000;
const STREAM_STABLE_MS = 1_000;

function readSignalCursor(): string | null {
  try {
    const cursor = localStorage.getItem(SIGNAL_STREAM_CURSOR_KEY);
    if (!cursor || cursor.length > 256 || /[\r\n\0]/.test(cursor)) return null;
    return cursor;
  } catch {
    return null;
  }
}

function persistSignalCursor(cursor: string): void {
  if (!cursor || cursor.length > 256 || /[\r\n\0]/.test(cursor)) return;
  try {
    localStorage.setItem(SIGNAL_STREAM_CURSOR_KEY, cursor);
  } catch {
    // Cursor persistence is best-effort; the live stream remains usable.
  }
}

function clearSignalCursor(): void {
  try {
    localStorage.removeItem(SIGNAL_STREAM_CURSOR_KEY);
  } catch {
    // Cursor persistence is best-effort; the live stream remains usable.
  }
}

async function consumeSseStream(
  body: ReadableStream<Uint8Array>,
  signal: AbortSignal,
  onEvent: (event: ParsedSseEvent) => boolean,
  onValidFrame: () => void,
): Promise<void> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let eventType = "message";
  let eventId: string | undefined;
  let dataLines: string[] = [];

  const resetEvent = () => {
    eventType = "message";
    eventId = undefined;
    dataLines = [];
  };
  const dispatchEvent = () => {
    if (dataLines.length > 0) {
      const isValid = onEvent({ type: eventType, data: dataLines.join("\n"), id: eventId });
      if (isValid) onValidFrame();
    }
    resetEvent();
  };
  const processLine = (rawLine: string) => {
    const line = rawLine.endsWith("\r") ? rawLine.slice(0, -1) : rawLine;
    if (line === "") {
      dispatchEvent();
      return;
    }
    if (line.startsWith(":")) return;

    const separator = line.indexOf(":");
    const field = separator === -1 ? line : line.slice(0, separator);
    const rawValue = separator === -1 ? "" : line.slice(separator + 1);
    const value = rawValue.startsWith(" ") ? rawValue.slice(1) : rawValue;
    if (field === "event") eventType = value || "message";
    if (field === "data") dataLines.push(value);
    if (field === "id" && !value.includes("\0")) eventId = value;
  };
  const cancelReader = () => {
    void reader.cancel().catch(() => undefined);
  };
  signal.addEventListener("abort", cancelReader, { once: true });

  try {
    while (!signal.aborted) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      let newline = buffer.indexOf("\n");
      while (newline !== -1) {
        processLine(buffer.slice(0, newline));
        buffer = buffer.slice(newline + 1);
        newline = buffer.indexOf("\n");
      }
    }

    if (!signal.aborted) {
      buffer += decoder.decode();
      if (buffer) processLine(buffer);
      dispatchEvent();
    }
  } finally {
    signal.removeEventListener("abort", cancelReader);
    reader.releaseLock();
  }
}

export interface SignalStreamState {
  connected: boolean;
  authError: boolean;
  replayLoss: SignalReplayLoss | null;
  clearReplayLoss: () => void;
}

function streamIdFromEventCursor(cursor: string, eventId: number): string | null {
  const separator = cursor.lastIndexOf(":");
  if (separator <= 0) return null;
  const streamId = cursor.slice(0, separator).trim();
  const sequence = Number(cursor.slice(separator + 1));
  if (
    !streamId
    || streamId.length > 256
    || /[\r\n\0]/.test(streamId)
    || !Number.isSafeInteger(sequence)
    || sequence !== eventId
  ) {
    return null;
  }
  return streamId;
}

function isEventStreamResponse(response: Response): boolean {
  const contentType = response.headers.get("Content-Type");
  return contentType?.split(";", 1)[0]?.trim().toLowerCase() === "text/event-stream";
}

export function useSignalStream(
  onSignal: (signal: SignalEvent) => void,
  enabled = true,
): SignalStreamState {
  const mode = useModeStore((s) => s.mode);
  const authToken = useAuthStore((s) => s.token);
  const apiKey = useConnectionStore((s) => s.apiKey);
  const [connected, setConnected] = useState(false);
  const [authError, setAuthError] = useState(false);
  const [replayLoss, setReplayLoss] = useState<SignalReplayLoss | null>(null);
  const qc = useQueryClient();
  const callbackRef = useRef(onSignal);
  callbackRef.current = onSignal;
  const modeRef = useRef(mode);
  modeRef.current = mode;

  const clearReplayLoss = useCallback(() => setReplayLoss(null), []);

  useEffect(() => {
    if (mode === "explore" || !enabled) {
      setConnected(false);
      setAuthError(false);
      return;
    }

    const base = getBase();
    const url = `${base}/api/v1/signals/stream`;
    const streamMode = mode;
    let disposed = false;
    let retryAttempt = 0;
    let retryTimer: ReturnType<typeof setTimeout> | null = null;
    let controller: AbortController | null = null;

    const handleEvent = (event: ParsedSseEvent): boolean => {
      if (disposed || modeRef.current !== streamMode) return false;
      if (event.type === "replay-loss") {
        const control = safeParse(event.data, signalReplayLossSchema);
        if (!control) return false;
        clearSignalCursor();
        setReplayLoss(control);
        void qc.resetQueries({ queryKey: ["signals", "recent"] });
        return true;
      }
      if (event.type !== "message") return false;

      const parsedSignal = safeParse(event.data, signalEventSchema);
      if (!parsedSignal) return false;
      const streamId = event.id
        ? streamIdFromEventCursor(event.id, parsedSignal.event_id)
        : parsedSignal.stream_id ?? null;
      if (event.id && !streamId) return false;
      const signal = streamId
        ? { ...parsedSignal, stream_id: streamId }
        : parsedSignal;
      callbackRef.current(signal);
      if (event.id) persistSignalCursor(event.id);
      return true;
    };

    const scheduleReconnect = () => {
      if (disposed || retryTimer !== null) return;
      const delay = Math.min(
        STREAM_RETRY_BASE_MS * 2 ** retryAttempt,
        STREAM_RETRY_MAX_MS,
      );
      retryAttempt += 1;
      retryTimer = setTimeout(() => {
        retryTimer = null;
        void connect();
      }, delay);
    };

    async function connect(): Promise<void> {
      const connectionController = new AbortController();
      controller = connectionController;
      const cursor = readSignalCursor();
      const headers: Record<string, string> = {
        ...buildHeaders(false),
        Accept: "text/event-stream",
      };
      if (cursor) headers["Last-Event-ID"] = cursor;

      try {
        const response = await fetch(url, {
          headers,
          signal: connectionController.signal,
        });
        if (disposed || modeRef.current !== streamMode) return;
        if (response.status === 401 || response.status === 403) {
          setConnected(false);
          setAuthError(true);
          return;
        }
        if (!response.ok) {
          throw new Error(`Signal stream HTTP ${response.status}`);
        }
        if (!isEventStreamResponse(response)) {
          void response.body?.cancel().catch(() => undefined);
          throw new Error("Signal stream response is not an event stream");
        }
        if (!response.body) {
          throw new Error("Signal stream response has no body");
        }

        setAuthError(false);
        let healthy = false;
        const markHealthy = () => {
          if (healthy || disposed || modeRef.current !== streamMode) return;
          healthy = true;
          retryAttempt = 0;
          setConnected(true);
        };
        const stableTimer = setTimeout(markHealthy, STREAM_STABLE_MS);
        try {
          await consumeSseStream(
            response.body,
            connectionController.signal,
            handleEvent,
            markHealthy,
          );
        } finally {
          clearTimeout(stableTimer);
        }
        if (disposed || connectionController.signal.aborted) return;
        setConnected(false);
        scheduleReconnect();
      } catch {
        if (disposed || connectionController.signal.aborted) return;
        setConnected(false);
        scheduleReconnect();
      }
    }

    setAuthError(false);
    setConnected(false);
    void connect();
    return () => {
      disposed = true;
      if (retryTimer !== null) clearTimeout(retryTimer);
      controller?.abort();
    };
  }, [apiKey, authToken, enabled, mode, qc]);

  return { connected, authError, replayLoss, clearReplayLoss };
}
