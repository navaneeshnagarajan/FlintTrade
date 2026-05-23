/**
 * useTickerFallback
 *
 * REST polling fallback for tick data when the WebSocket is disconnected.
 *
 * Design:
 *   - Watches `wsConnected` from connectionStore
 *   - When WS is DOWN: polls `getTicker` every 5 s for the instruments currently
 *     subscribed to the WS service (ltp mode only, capped at MAX_INSTRUMENTS)
 *   - When WS comes back UP: clears the interval immediately
 *   - Writes results to the same `tickAtomFamily` atoms the WS bridge writes to,
 *     using the identical key format "{exchange}:{symbol}" (display-name keys)
 *
 * Atom key convention (must match useWsBridge + marketAtoms):
 *   Indices  → "NSE_INDEX:NIFTY", "BSE_INDEX:SENSEX", etc.
 *   MCX      → "MCX:GOLD", "MCX:SILVER", etc.   (display names, not futures suffixes)
 *   Equities → "NSE:RELIANCE", "NSE:INFY", etc.
 *
 * For MCX the WS bridge resolves nearest-futures contracts internally and maps
 * their tick keys back to display-name atom keys. Here we poll with the
 * display-name symbol ("GOLD", exchange "MCX") directly — the OpenAlgo ticker
 * endpoint resolves the nearest contract on its side and returns data for it.
 * The Quote response carries { symbol: "GOLD", exchange: "MCX" } so the atom
 * key built here will always be "MCX:GOLD", matching the display-name atom.
 *
 * Composition:
 *   Add <useTickerFallback /> call in the same component that calls useWsBridge()
 *   (currently App.tsx or the root provider). Both hooks are independent — they
 *   share only the Jotai store and the connectionStore.
 */

import { useEffect, useRef } from "react";
import { useStore } from "jotai";
import { tickAtomFamily } from "@/atoms/marketAtoms";
import { useConnectionStore } from "@/stores/connectionStore";
import { getWsService } from "@/services/websocket";
import { getTicker } from "@/services/api";
import type { WsTick, WsInstrument } from "@/types/api";

/** Maximum instruments to poll simultaneously to stay within the 50/s rate limit. */
const MAX_INSTRUMENTS = 10;

/** Poll interval in milliseconds when WebSocket is disconnected. */
const POLL_INTERVAL_MS = 5_000;

/**
 * Build the atom key from a WsInstrument.
 * Must match the key format used in tickAtomFamily and useWsBridge.
 */
function instrumentKey(inst: WsInstrument): string {
  return `${inst.exchange}:${inst.symbol}`;
}

export function useTickerFallback(): void {
  const wsConnected = useConnectionStore((s) => s.wsConnected);
  const store = useStore();

  // Stable ref so the interval callback always has the latest connected flag
  // without needing to be re-created on every render.
  const wsConnectedRef = useRef(wsConnected);
  useEffect(() => {
    wsConnectedRef.current = wsConnected;
  }, [wsConnected]);

  useEffect(() => {
    // WS is connected — no fallback needed right now.
    if (wsConnected) return;

    // Grab subscribed instruments from the WS service (ltp subscriptions only).
    // getWsService() may return null if the service was never initialised (e.g.
    // before wsUrl is set). Guard with optional chaining.
    const ws = getWsService();
    if (!ws) return;

    const allSubscribed = ws.getSubscriptions("ltp");
    if (allSubscribed.length === 0) return;

    // Cap at MAX_INSTRUMENTS to respect the 50/s general rate limit.
    const instruments: WsInstrument[] = allSubscribed.slice(0, MAX_INSTRUMENTS);

    // One immediate poll so the UI gets data right away on disconnect.
    void pollAll(instruments, store);

    const timer = setInterval(() => {
      // Double-check inside the interval: if WS reconnected, bail early and let
      // the interval clear on the next effect run. This avoids a race where the
      // interval fires one extra time after WS comes back.
      if (wsConnectedRef.current) return;

      void pollAll(instruments, store);
    }, POLL_INTERVAL_MS);

    return () => {
      clearInterval(timer);
    };
  // Re-run when connection drops (wsConnected flips false) or on mount.
  // We intentionally exclude `store` from the deps array because useStore()
  // returns a stable reference for the lifetime of the Provider.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [wsConnected]);
}

/**
 * Poll getTicker for each instrument and write results into Jotai atoms.
 * Errors per-instrument are swallowed so one bad symbol does not block others.
 */
async function pollAll(
  instruments: WsInstrument[],
  store: ReturnType<typeof useStore>,
): Promise<void> {
  await Promise.allSettled(
    instruments.map(async (inst) => {
      try {
        const quote = await getTicker(inst.symbol, inst.exchange);

        // Map Quote → WsTick (Quote is a strict superset of WsTick's required fields)
        const tick: WsTick = {
          symbol: quote.symbol,
          exchange: quote.exchange,
          ltp: quote.ltp,
          open: quote.open,
          high: quote.high,
          low: quote.low,
          close: quote.close,
          volume: quote.volume,
          change: quote.change,
          pct: quote.pct,
        };

        // Write to the same atom the WS bridge writes to.
        // Key uses the instrument display name, matching useWsBridge + marketAtoms.
        const key = instrumentKey(inst);
        store.set(tickAtomFamily(key), tick);
      } catch {
        // Swallow per-instrument errors — expected during broker downtime / pre-market.
      }
    }),
  );
}
