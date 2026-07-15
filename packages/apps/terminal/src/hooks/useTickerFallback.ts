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
 *   - Publishes an honest health report (staleness + truncation) via the hook's
 *     return value AND the exported `tickerFallbackStatusAtom`, so consumers can
 *     show "data is stale" / "N symbols not refreshed" instead of silently
 *     rendering frozen prices as live.
 *
 * Cap policy (no silent lies):
 *   REST polling is capped at MAX_INSTRUMENTS to respect the 50/s rate limit.
 *   When more instruments are subscribed than the cap allows, instruments are
 *   prioritised — the terminal-wide selected instrument first (it drives the
 *   chart/OrderPad), then always-visible index instruments (ticker bar), then
 *   the remainder most-recently-subscribed first (an MRU proxy: the newest
 *   subscriptions belong to the widgets currently on screen). Whatever falls
 *   beyond the cap is reported in `droppedKeys`/`truncated` — those atoms are
 *   NOT refreshed while the WS is down.
 *
 * Atom key convention (must match useWsBridge + marketAtoms):
 *   Indices  → "NSE_INDEX:NIFTY", "BSE_INDEX:SENSEX", etc.
 *   MCX      → "MCX:GOLD", "MCX:SILVER", etc.   (display names, not futures suffixes)
 *   Equities → "NSE:RELIANCE", "NSE:INFY", etc.
 *
 * For MCX the WS bridge resolves nearest-futures contracts internally and maps
 * their tick keys back to display-name atom keys. The WS subscription list
 * therefore contains the FULL futures symbol (e.g. "GOLD02APR26FUT"); when the
 * fallback polls such an instrument it mirrors the bridge's routing and writes
 * the result to the display-name atom ("MCX:GOLD"), never to the (unread)
 * futures-suffix key.
 *
 * Composition:
 *   Call useTickerFallback() in the same component that calls useWsBridge()
 *   (currently AppLayout). Both hooks are independent — they share only the
 *   Jotai store and the connectionStore.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { atom, useStore } from "jotai";
import { tickAtomFamily, selectedSymbolAtom } from "@/atoms/marketAtoms";
import { useConnectionStore } from "@/stores/connectionStore";
import { getWsService } from "@/services/websocket";
import { getTicker } from "@/services/api";
import type { WsTick, WsInstrument } from "@/types/api";

/** Maximum instruments to poll simultaneously to stay within the 50/s rate limit. */
export const MAX_INSTRUMENTS = 10;

/** Poll interval in milliseconds when WebSocket is disconnected. */
const POLL_INTERVAL_MS = 5_000;

/**
 * Fallback data older than this is reported stale (two missed poll cycles).
 * Exported so consumers rendering staleness affordances agree on the window.
 */
export const STALE_AFTER_MS = POLL_INTERVAL_MS * 2;

/** Health report for the REST tick fallback — no silent lies. */
export interface TickerFallbackStatus {
  /** True while the WS is down and REST polling is running. */
  active: boolean;
  /** `Date.now()` of the last successful REST tick write; null = none yet. */
  lastUpdatedAt: number | null;
  /**
   * True when the WS is down and no fresh fallback data has landed within
   * `STALE_AFTER_MS` — tick atoms may be showing frozen prices.
   */
  isStale: boolean;
  /** Atom keys ("EXCHANGE:SYMBOL") the fallback is actively refreshing. */
  polledKeys: string[];
  /** Subscribed atom keys beyond the REST cap that are NOT being refreshed. */
  droppedKeys: string[];
  /** True when at least one subscribed instrument exceeded the cap. */
  truncated: boolean;
}

const INITIAL_STATUS: TickerFallbackStatus = {
  active: false,
  lastUpdatedAt: null,
  isStale: false,
  polledKeys: [],
  droppedKeys: [],
  truncated: false,
};

/**
 * Read-only mirror of the fallback health report. Any widget can subscribe
 * (e.g. to render a "stale data" badge) without prop-drilling from AppLayout.
 * Written exclusively by useTickerFallback.
 */
export const tickerFallbackStatusAtom = atom<TickerFallbackStatus>(INITIAL_STATUS);

/**
 * Build the atom key from a WsInstrument.
 * Must match the key format used in tickAtomFamily and useWsBridge.
 */
function instrumentKey(inst: WsInstrument): string {
  return `${inst.exchange}:${inst.symbol}`;
}

/** Matches MCX nearest-futures symbols, e.g. "GOLD02APR26FUT" → "GOLD". */
const MCX_FUTURES_SUFFIX = /^([A-Z]+?)\d{2}[A-Z]{3}\d{2}FUT$/;

/**
 * The atom key the tick should be WRITTEN to. Mirrors the WS bridge's
 * futures→display routing so an MCX futures subscription refreshes the
 * display-name atom ("MCX:GOLD") that widgets actually read.
 */
function displayKey(inst: WsInstrument): string {
  if (inst.exchange === "MCX") {
    const match = MCX_FUTURES_SUFFIX.exec(inst.symbol);
    if (match) return `${inst.exchange}:${match[1]}`;
  }
  return instrumentKey(inst);
}

/**
 * Order subscribed instruments by fallback priority and split at the cap.
 *
 * Priority: (1) the terminal-wide selected instrument, (2) always-visible
 * index instruments (ticker bar), (3) the remainder most-recently-subscribed
 * first. Exported for tests.
 */
export function prioritiseFallbackInstruments(
  subscribed: WsInstrument[],
  selected: WsInstrument | null,
  cap: number = MAX_INSTRUMENTS,
): { polled: WsInstrument[]; dropped: WsInstrument[] } {
  const seen = new Set<string>();
  const ordered: WsInstrument[] = [];
  const push = (inst: WsInstrument) => {
    const key = instrumentKey(inst);
    if (seen.has(key)) return;
    seen.add(key);
    ordered.push(inst);
  };

  // 1. The selected instrument drives the chart/OrderPad — always first.
  if (selected?.symbol && selected.exchange) {
    push({ symbol: selected.symbol, exchange: selected.exchange });
  }
  // 2. Index instruments back the always-visible ticker bar.
  for (const inst of subscribed) {
    if (inst.exchange.endsWith("_INDEX")) push(inst);
  }
  // 3. Everything else, most recently subscribed first (MRU proxy).
  for (let i = subscribed.length - 1; i >= 0; i -= 1) push(subscribed[i]);

  return { polled: ordered.slice(0, cap), dropped: ordered.slice(cap) };
}

export function useTickerFallback(enabled = true): TickerFallbackStatus {
  const wsConnected = useConnectionStore((s) => s.wsConnected);
  const store = useStore();
  const [status, setStatus] = useState<TickerFallbackStatus>(INITIAL_STATUS);

  // Stable ref so the interval callback always has the latest connected flag
  // without needing to be re-created on every render.
  const wsConnectedRef = useRef(wsConnected);
  useEffect(() => {
    if (!enabled) {
      publish(INITIAL_STATUS);
      return;
    }

    wsConnectedRef.current = wsConnected;
  }, [wsConnected]);

  // Survives WS outages within the hook's lifetime so staleness is measured
  // from the last real data write, not from when the current outage began.
  const lastUpdatedAtRef = useRef<number | null>(null);

  // Publish every status change to both the local state (hook return) and the
  // shared atom (any-widget consumption).
  const publish = useCallback(
    (next: TickerFallbackStatus) => {
      setStatus(next);
      store.set(tickerFallbackStatusAtom, next);
    },
    [store],
  );

  useEffect(() => {
    // WS is connected — fallback inactive; live staleness is the WS service's
    // concern (diagnostics.tickAgeMs), not this hook's.
    if (wsConnected) {
      publish(INITIAL_STATUS);
      return;
    }

    // Grab subscribed instruments from the WS service (ltp subscriptions only).
    // getWsService() may return null if the service was never initialised (e.g.
    // before wsUrl is set).
    const ws = getWsService();
    if (!ws) return;

    const allSubscribed = ws.getSubscriptions("ltp");
    if (allSubscribed.length === 0) return;

    const { polled, dropped } = prioritiseFallbackInstruments(
      allSubscribed,
      store.get(selectedSymbolAtom),
    );
    const polledKeys = polled.map(displayKey);
    const droppedKeys = dropped.map(displayKey);

    const report = () => {
      const lastUpdatedAt = lastUpdatedAtRef.current;
      publish({
        active: true,
        lastUpdatedAt,
        isStale: lastUpdatedAt === null || Date.now() - lastUpdatedAt > STALE_AFTER_MS,
        polledKeys,
        droppedKeys,
        truncated: droppedKeys.length > 0,
      });
    };

    const runPoll = async () => {
      const successes = await pollAll(polled, store);
      if (successes > 0) lastUpdatedAtRef.current = Date.now();
      report();
    };

    // Honest initial report (stale until the first poll lands), then an
    // immediate poll so the UI gets data right away on disconnect.
    report();
    void runPoll();

    const timer = setInterval(() => {
      // Double-check inside the interval: if WS reconnected, bail early and let
      // the interval clear on the next effect run. This avoids a race where the
      // interval fires one extra time after WS comes back.
      if (wsConnectedRef.current) return;

      void runPoll();
    }, POLL_INTERVAL_MS);

    return () => {
      clearInterval(timer);
    };
  // Re-run when connection drops (wsConnected flips false) or on mount.
  // We intentionally exclude `store` from the deps array because useStore()
  // returns a stable reference for the lifetime of the Provider.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled, wsConnected, publish]);

  return status;
}

/**
 * Poll getTicker for each instrument and write results into Jotai atoms.
 * Errors per-instrument are swallowed so one bad symbol does not block others.
 *
 * @returns The number of instruments whose atoms were successfully refreshed.
 */
async function pollAll(
  instruments: WsInstrument[],
  store: ReturnType<typeof useStore>,
): Promise<number> {
  let successes = 0;
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

        // Write to the same atom the WS bridge writes to. The key uses the
        // instrument display name (MCX futures suffixes are mapped back),
        // matching useWsBridge + marketAtoms.
        store.set(tickAtomFamily(displayKey(inst)), tick);
        successes += 1;
      } catch {
        // Swallow per-instrument errors — expected during broker downtime / pre-market.
      }
    }),
  );
  return successes;
}
