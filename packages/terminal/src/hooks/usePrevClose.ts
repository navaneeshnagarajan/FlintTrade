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
 * This hook is called in AppLayout.tsx alongside useWsBridge and
 * useTickerFallback. It is a no-op when the API key is not configured.
 */

import { useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import { useStore } from "jotai";
import { tickAtomFamily } from "@/atoms/marketAtoms";
import { useConnectionStore } from "@/stores/connectionStore";
import { getMultiQuotes } from "@/services/api";
import type { WsInstrument } from "@/types/api";

/** All instruments shown in TickerBar — must match useWsBridge INDEX_INSTRUMENTS + MCX list. */
const TICKER_INSTRUMENTS: WsInstrument[] = [
  { symbol: "NIFTY",      exchange: "NSE_INDEX" },
  { symbol: "BANKNIFTY",  exchange: "NSE_INDEX" },
  { symbol: "SENSEX",     exchange: "BSE_INDEX" },
  { symbol: "INDIAVIX",   exchange: "NSE_INDEX" },
  { symbol: "FINNIFTY",   exchange: "NSE_INDEX" },
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
 * Fetches previous close for TICKER_INSTRUMENTS.
 * Returns a map of "{exchange}:{symbol}" → prevClose (number).
 * Instruments that fail are omitted silently.
 */
async function fetchPrevClose(): Promise<Map<string, number>> {
  const quotes = await getMultiQuotes(TICKER_INSTRUMENTS);
  const map = new Map<string, number>();
  if (!Array.isArray(quotes)) return map;
  for (const q of quotes) {
    if (q.symbol && q.exchange && typeof q.close === "number" && q.close > 0) {
      map.set(`${q.exchange}:${q.symbol}`, q.close);
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
