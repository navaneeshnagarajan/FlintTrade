/** Seeds the prior session reference for native market prices.
 * Cache identity follows the selected native account and never trusts late
 * results from a previous account. Current quotes retain their LTP.
 */
import { useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import { useStore } from "jotai";
import { tickAtomFamily } from "@/atoms/marketAtoms";
import { useBrokerConnected } from "@/hooks/useBrokerConnected";
import { useMarketDataScope, requireCurrentMarketDataScope, MarketDataAuthorityChangedError } from "@/hooks/useDataScope";
import { useMarketObservationEpoch } from "@/hooks/useMarketObservationEpoch";
import { getMultiQuotes, getQuotes } from "@/services/api";
import type { Quote, WsInstrument } from "@/types/api";

/** All instruments shown in TickerBar — must match useWsBridge INDEX_INSTRUMENTS + MCX list. */
const TICKER_INSTRUMENTS: WsInstrument[] = [
  { symbol: "NIFTY",      exchange: "NSE_INDEX" },
  { symbol: "BANKNIFTY",  exchange: "NSE_INDEX" },
  { symbol: "SENSEX",     exchange: "BSE_INDEX" },
  { symbol: "INDIAVIX",   exchange: "NSE_INDEX" },
  { symbol: "FINNIFTY",   exchange: "NSE_INDEX" },
  { symbol: "NIFTYIT",    exchange: "NSE_INDEX" },
  // Commodity reference reads are best-effort; unresolved display names
  // leave the prior session reference unavailable.
  { symbol: "GOLD",       exchange: "MCX" },
  { symbol: "SILVER",     exchange: "MCX" },
  { symbol: "CRUDEOIL",   exchange: "MCX" },
  { symbol: "NATURALGAS", exchange: "MCX" },
];

/** 5 minutes — prevClose is static for the entire trading day. */
const STALE_TIME_MS = 5 * 60 * 1000;

/**
 * Extracts the previous close price from a Quote response.
 * broker returns `prev_close` (previous session close). Some broker
 * adapters omit it and use `close` instead — we fall back to that.
 * Returns undefined if neither field is a positive number.
 */
function extractPrevClose(q: Quote): number | undefined {
  if (typeof q.prev_close === "number" && Number.isFinite(q.prev_close) && q.prev_close > 0) return q.prev_close;
  if (typeof q.close === "number" && Number.isFinite(q.close) && q.close > 0) return q.close;
  return undefined;
}

/**
 * Fallback: fetch previous close for each instrument individually.
 * Staggered at 100ms intervals to avoid saturating the 50/s rate limit
 * when multiquotes is unavailable or returns partial data.
 */
async function fetchPrevCloseIndividually(
  missing: WsInstrument[],
  signal: AbortSignal,
  scope: string,
  requireAuthority: () => void,
): Promise<Map<string, number>> {
  const map = new Map<string, number>();
  for (let i = 0; i < missing.length; i++) {
    const { symbol, exchange } = missing[i];
    try {
      // Stagger requests: 0ms, 100ms, 200ms …
      if (i > 0) await new Promise((r) => setTimeout(r, 100));
      signal.throwIfAborted();
      requireAuthority();
      const q = await getQuotes(symbol, exchange, signal, scope);
      signal.throwIfAborted();
      requireAuthority();
      const prevClose = extractPrevClose(q);
      if (prevClose !== undefined) {
        map.set(`${exchange}:${symbol}`, prevClose);
      }
    } catch {
      signal.throwIfAborted();
      requireAuthority();
      // Skip this instrument — not a fatal error
    }
  }
  return map;
}

/**
 * Fetches previous close for TICKER_INSTRUMENTS.
 * Tries multiquotes first; falls back to individual getQuotes calls if
 * multiquotes fails or returns an empty array.
 * Returns a map of "{exchange}:{symbol}" → prevClose (number).
 */
async function fetchPrevClose(signal: AbortSignal, scope: string, requireAuthority: () => void): Promise<Map<string, number>> {
  const map = new Map<string, number>();

  // --- Primary path: multiquotes ---
  // The native API client exposes normalised quotes.
  // The post<T> helper returns json.data ?? json, so we get the raw response object.
  try {
    const result = await getMultiQuotes(TICKER_INSTRUMENTS, signal, scope) as unknown;
    signal.throwIfAborted();
    requireAuthority();
    // Handle both array and { results: [] } shapes
    const items: Array<Record<string, unknown>> =
      Array.isArray(result) ? result
      : (result && typeof result === "object" && "results" in result && Array.isArray((result as Record<string, unknown>).results))
        ? (result as Record<string, unknown>).results as Array<Record<string, unknown>>
        : [];

    for (const item of items) {
      // Each item may be { symbol, exchange, data: { prev_close, close, ltp, ... } }
      // or a flat quote object { symbol, exchange, prev_close, close, ltp, ... }
      const sym = (item.symbol as string) || "";
      const exch = (item.exchange as string) || "";
      if (!sym || !exch) continue;

      // The quote data may be nested under 'data' or flat
      const quoteData = (item.data && typeof item.data === "object" ? item.data : item) as Record<string, unknown>;
      const prevClose = extractPrevClose(quoteData as unknown as Quote);
      if (prevClose !== undefined) {
        map.set(`${exch}:${sym}`, prevClose);
      }
    }
  } catch {
    signal.throwIfAborted();
    requireAuthority();
    // multiquotes failed — fall through to individual fallback below
  }

  // --- Fallback path: individual getQuotes for any missing instruments ---
  const missing = TICKER_INSTRUMENTS.filter(
    ({ symbol, exchange }) => !map.has(`${exchange}:${symbol}`),
  );
  if (missing.length > 0) {
    const fallbackMap = await fetchPrevCloseIndividually(missing, signal, scope, requireAuthority);
    for (const [key, val] of fallbackMap) {
      map.set(key, val);
    }
  }

  return map;
}

export function usePrevClose(enabled = true): void {
  const connected = useBrokerConnected();
  const scope = useMarketDataScope();
  const { epoch, currentEpoch } = useMarketObservationEpoch();
  const store = useStore();
  const requireAuthority = () => {
    if (currentEpoch.current !== epoch) throw new MarketDataAuthorityChangedError();
    requireCurrentMarketDataScope(scope);
  };

  const { data: prevCloseMap } = useQuery<Map<string, number>>({
    queryKey: ["prevClose", scope, "tickerInstruments", epoch],
    queryFn: async ({ signal }) => {
      requireAuthority();
      const result = await fetchPrevClose(signal, scope, requireAuthority);
      signal.throwIfAborted();
      requireAuthority();
      return result;
    },
    staleTime: STALE_TIME_MS,
    enabled: enabled && connected,
    // Retry once on failure; these are static data, no need for aggressive retries
    retry: 1,
  });

  // Merge prevClose into tick atoms whenever query data arrives.
  // We do NOT overwrite ltp — only add/update the prevClose field.
  useEffect(() => {
    if (!enabled || !connected || !prevCloseMap || prevCloseMap.size === 0) return;
    if (currentEpoch.current !== epoch) return;
    try { requireCurrentMarketDataScope(scope); } catch { return; }

    for (const [key, prevClose] of prevCloseMap) {
      const atom = tickAtomFamily(key);
      store.set(atom, (current) => {
        if (current !== null) return { ...current, prevClose };
        const colonIdx = key.indexOf(":");
        return { symbol: key.slice(colonIdx + 1), exchange: key.slice(0, colonIdx), ltp: 0, prevClose };
      }, scope);
    }
  }, [enabled, connected, scope, epoch, currentEpoch, prevCloseMap, store]);
}
