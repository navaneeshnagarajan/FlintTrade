/** Native quote polling for the instruments currently displayed by the terminal.
 * Quotes share the Jotai tick cache and local listeners. Each poll belongs to
 * one captured market authority; account changes discard its pending results.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { atom, useStore } from "jotai";
import { tickAtomFamily } from "@/atoms/marketAtoms";
import { channelInstrumentAtoms, USER_CHANNELS } from "@/services/fdc3/channels";
import { useConnectionStore } from "@/stores/connectionStore";
import { getWsService } from "@/services/websocket";
import { getTicker } from "@/services/api";
import { useMarketDataScope, requireCurrentMarketDataScope } from "@/hooks/useDataScope";
import { useMarketObservationEpoch } from "@/hooks/useMarketObservationEpoch";
import { FEED_STALE_AFTER_MS } from "@/lib/feedFreshness";
import type { WsTick, WsInstrument } from "@/types/api";

/** Maximum instruments to poll simultaneously to stay within the 50/s rate limit. */
export const MAX_INSTRUMENTS = 10;

/** Native REST quote polling interval in milliseconds. */
const POLL_INTERVAL_MS = 5_000;

/**
 * Fallback data older than this is reported stale (two missed poll cycles).
 * Same window as the TopBar / ticker / Market Clock source chip.
 */
export const STALE_AFTER_MS = FEED_STALE_AFTER_MS;

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
 * The atom key the tick should be WRITTEN to. Uses the local registry's
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
 * Priority: (1) the instruments on the FDC3 user channels (red first — the
 * legacy terminal-wide selection), (2) always-visible index instruments
 * (ticker bar), (3) the remainder most-recently-subscribed first. Exported
 * for tests.
 */
export function prioritiseFallbackInstruments(
  subscribed: WsInstrument[],
  selected: WsInstrument | null | Array<WsInstrument | null>,
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

  // 1. Channel instruments drive charts/OrderPads — always first.
  for (const inst of Array.isArray(selected) ? selected : [selected]) {
    if (inst?.symbol && inst.exchange) {
      push({ symbol: inst.symbol, exchange: inst.exchange });
    }
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
  const scope = useMarketDataScope();
  const { epoch, currentEpoch } = useMarketObservationEpoch();
  const [status, setStatus] = useState<TickerFallbackStatus>(INITIAL_STATUS);

  // Publish every status change to both the local state (hook return) and the
  // shared atom (any-widget consumption). Declared before its first consumer so
  // that consumer can name it as a dependency without a temporal-dead-zone
  // reference in the dependency array.
  const publish = useCallback(
    (next: TickerFallbackStatus) => {
      setStatus(next);
      store.set(tickerFallbackStatusAtom, next);
    },
    [store],
  );

  // Stable ref so the interval callback always has the latest connected flag
  // without needing to be re-created on every render.
  const wsConnectedRef = useRef(wsConnected);
  useEffect(() => {
    if (!enabled) {
      publish(INITIAL_STATUS);
      return;
    }

    wsConnectedRef.current = wsConnected;
    // `enabled` was missing here: flipping the hook off without the connection
    // also changing left the reset above unpublished, so consumers kept reading
    // the last fallback status of a hook that was no longer running.
  }, [wsConnected, enabled, publish]);

  // Survives WS outages within the hook's lifetime so staleness is measured
  // from the last real data write, not from when the current outage began.
  const lastUpdatedAtRef = useRef<number | null>(null);

  useEffect(() => {
    if (!enabled) return;
    // WS is connected — fallback inactive; live staleness is the WS service's
    // concern (diagnostics.tickAgeMs), not this hook's.
    if (wsConnected) {
      publish(INITIAL_STATUS);
      return;
    }

    // Grab subscribed instruments from the WS service (ltp subscriptions only).
    // getWsService() may return null if the service was never initialised (e.g.
    // before a stream is available).
    const ws = getWsService();
    if (!ws) return;

    let cancelled = false;
    let polling = false;
    let polledKeys: string[] = [];
    let droppedKeys: string[] = [];
    const report = () => {
      if (cancelled) return;
      const lastUpdatedAt = lastUpdatedAtRef.current;
      publish({ active: polledKeys.length > 0, lastUpdatedAt,
        isStale: polledKeys.length > 0 && (lastUpdatedAt === null || Date.now() - lastUpdatedAt > STALE_AFTER_MS),
        polledKeys, droppedKeys, truncated: droppedKeys.length > 0 });
    };
    const current = () => {
      if (cancelled || currentEpoch.current !== epoch) return false;
      try { requireCurrentMarketDataScope(scope); return true; } catch { return false; }
    };
    const runPoll = async () => {
      if (polling || !current()) return;
      // Widget interests change without remounting AppLayout. Read them anew
      // each cycle so closing or changing a widget releases its polling work.
      const subscribed = [...new Map([...ws.getSubscriptions("ltp"), ...ws.getSubscriptions("quote")]
        .map((instrument) => [instrumentKey(instrument), instrument])).values()];
      const { polled, dropped } = prioritiseFallbackInstruments(subscribed,
        USER_CHANNELS.map((channel) => store.get(channelInstrumentAtoms[channel.id])));
      polledKeys = polled.map(displayKey);
      droppedKeys = dropped.map(displayKey);
      report();
      polling = true;
      try {
        const successes = await pollAll(polled, store, current, scope);
        if (!current()) return;
        if (successes > 0) lastUpdatedAtRef.current = Date.now();
        report();
      } finally { polling = false; }
    };
    lastUpdatedAtRef.current = null;
    if (typeof document === "undefined" || !document.hidden) void runPoll();
    const timer = setInterval(() => {
      if (wsConnectedRef.current || document.hidden) return;
      void runPoll();
    }, POLL_INTERVAL_MS);

    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  // Re-run on a feed or authority change.
  }, [enabled, wsConnected, publish, scope, store, epoch, currentEpoch]);

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
  current: () => boolean,
  scope: string,
): Promise<number> {
  let successes = 0;
  await Promise.allSettled(
    instruments.map(async (inst) => {
      try {
        const quote = await getTicker(inst.symbol, inst.exchange);
        if (!current()) return;

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

        // Write to the shared native observation atom. The key uses the
        // instrument display name (MCX futures suffixes are mapped back),
        // matching useWsBridge + marketAtoms.
        let merged = tick;
        store.set(tickAtomFamily(displayKey(inst)), (existing) => {
          const previousClose = quote.prev_close ?? existing?.prevClose;
          merged = previousClose !== undefined ? { ...tick, prevClose: previousClose } : tick;
          return merged;
        }, scope);
        if (current()) getWsService().publishTick?.(merged);
        successes += 1;
      } catch {
        // Swallow per-instrument errors — expected during broker downtime / pre-market.
      }
    }),
  );
  return successes;
}
