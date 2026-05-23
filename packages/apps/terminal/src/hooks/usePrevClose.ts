/**
 * usePrevClose
 *
 * Fetches the previous session close price for all TickerBar instruments
 * via REST /multiquotes on mount and stores it as `prevClose` in each
 * instrument's Jotai tickAtomFamily atom.
 *
 * Design rationale:
 *   - WebSocket LTP mode (mode=1) only delivers `ltp`. It does NOT deliver
 *     `close` / `prev_close` / `change` / `pct`. As a result, all percentage
 *     change displays in TickerBar and Dashboard show 0.00% until this hook
 *     fetches the REST data.
 *   - We fetch ONCE on mount (or on WS reconnect) via TanStack Query with a
 *     5-minute staleTime — previous close is a static value for the whole
 *     trading day.
 *   - On success we merge `prevClose` into each existing tick atom without
 *     overwriting live LTP data.
 *   - On failure we log a warning and leave atoms unchanged — TickerBar will
 *     show "—" instead of a misleading 0.00%.
 *
 * Field mapping:
 *   OpenAlgo returns `prev_close` (previous session close) and `close`
 *   (current session OHLC close). We read `prev_close` first; if absent we
 *   fall back to `close`. This handles broker adapters that conflate the two.
 *
 * Fallback strategy:
 *   If `multiquotes` fails (network error, rate limit) or returns fewer
 *   results than expected, we retry with individual `getQuotes()` calls
 *   staggered at 100ms intervals to stay within the 50/s general rate limit.
 *
 * This hook is called in AppLayout.tsx alongside useWsBridge and
 * useTickerFallback. It is a no-op when the API key is not configured.
 */

import { useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import { useStore } from "jotai";
import { tickAtomFamily } from "@/atoms/marketAtoms";
import { useConnectionStore } from "@/stores/connectionStore";
import { getMultiQuotes, getQuotes } from "@/services/api";
import type { Quote, WsInstrument } from "@/types/api";

/** All instruments shown in TickerBar — must match useWsBridge INDEX_INSTRUMENTS + MCX list. */
const TICKER_INSTRUMENTS: WsInstrument[] = [
  { symbol: "NIFTY",      exchange: "NSE_INDEX" },
  { symbol: "BANKNIFTY",  exchange: "NSE_INDEX" },
  { symbol: "SENSEX",     exchange: "BSE_INDEX" },
  { symbol: "INDIAVIX",   exchange: "NSE_INDEX" },
  // MCX commodities — OpenAlgo resolves nearest contract on its side when
  // queried by display name (GOLD, SILVER, etc.) via multiquotes.
  { symbol: "GOLD",       exchange: "MCX" },
  { symbol: "SILVER",     exchange: "MCX" },
  { symbol: "CRUDEOIL",   exchange: "MCX" },
  { symbol: "NATURALGAS", exchange: "MCX" },
];

/** 5 minutes — prevClose is static for the entire trading day. */
const STALE_TIME_MS = 5 * 60 * 1000;

/**
 * Extracts the previous close price from a Quote response.
 * OpenAlgo returns `prev_close` (previous session close). Some broker
 * adapters omit it and use `close` instead — we fall back to that.
 * Returns undefined if neither field is a positive number.
 */
function extractPrevClose(q: Quote): number | undefined {
  if (typeof q.prev_close === "number" && q.prev_close > 0) return q.prev_close;
  if (typeof q.close === "number" && q.close > 0) return q.close;
  return undefined;
}

/**
 * Fallback: fetch previous close for each instrument individually.
 * Staggered at 100ms intervals to avoid saturating the 50/s rate limit
 * when multiquotes is unavailable or returns partial data.
 */
async function fetchPrevCloseIndividually(
  missing: WsInstrument[],
): Promise<Map<string, number>> {
  const map = new Map<string, number>();
  for (let i = 0; i < missing.length; i++) {
    const { symbol, exchange } = missing[i];
    try {
      // Stagger requests: 0ms, 100ms, 200ms …
      if (i > 0) await new Promise((r) => setTimeout(r, 100));
      const q = await getQuotes(symbol, exchange);
      const prevClose = extractPrevClose(q);
      if (prevClose !== undefined) {
        map.set(`${exchange}:${symbol}`, prevClose);
      }
    } catch {
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
async function fetchPrevClose(): Promise<Map<string, number>> {
  const map = new Map<string, number>();

  // --- Primary path: multiquotes ---
  // OpenAlgo returns { results: [{ symbol, exchange, data: { prev_close, ... } }], status }
  // The post<T> helper returns json.data ?? json, so we get the raw response object.
  try {
    const result = await getMultiQuotes(TICKER_INSTRUMENTS) as unknown;
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
    // multiquotes failed — fall through to individual fallback below
  }

  // --- Fallback path: individual getQuotes for any missing instruments ---
  const missing = TICKER_INSTRUMENTS.filter(
    ({ symbol, exchange }) => !map.has(`${exchange}:${symbol}`),
  );
  if (missing.length > 0) {
    const fallbackMap = await fetchPrevCloseIndividually(missing);
    for (const [key, val] of fallbackMap) {
      map.set(key, val);
    }
  }

  return map;
}

export function usePrevClose(): void {
  const apiKey = useConnectionStore((s) => s.apiKey);
  const store = useStore();

  const { data: prevCloseMap } = useQuery<Map<string, number>>({
    queryKey: ["prevClose", "tickerInstruments"],
    queryFn: fetchPrevClose,
    staleTime: STALE_TIME_MS,
    // Only run when the API key is configured — avoids 401 errors pre-setup
    enabled: Boolean(apiKey),
    // Retry once on failure; these are static data, no need for aggressive retries
    retry: 1,
  });

  // Merge prevClose into tick atoms whenever query data arrives.
  // We do NOT overwrite ltp — only add/update the prevClose field.
  useEffect(() => {
    if (!prevCloseMap || prevCloseMap.size === 0) return;

    for (const [key, prevClose] of prevCloseMap) {
      const atom = tickAtomFamily(key);
      const current = store.get(atom);

      if (current !== null) {
        // Atom already has live tick data — merge prevClose in
        store.set(atom, { ...current, prevClose });
      } else {
        // No live tick yet — pre-seed a minimal tick with prevClose only.
        // We extract symbol/exchange from the key "{exchange}:{symbol}".
        const colonIdx = key.indexOf(":");
        if (colonIdx === -1) continue;
        const exchange = key.slice(0, colonIdx);
        const symbol = key.slice(colonIdx + 1);
        store.set(atom, {
          symbol,
          exchange,
          ltp: 0,
          prevClose,
        });
      }
    }
  }, [prevCloseMap, store]);
}
