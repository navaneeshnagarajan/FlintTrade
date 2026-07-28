import { useEffect } from "react";
import { useStore } from "jotai";
import { tickAtomFamily } from "@/atoms/marketAtoms";
import { channelInstrumentAtoms, USER_CHANNELS, type UserChannelId } from "@/services/fdc3/channels";
import { useConnectionStore } from "@/stores/connectionStore";
import { getWsService } from "@/services/websocket";
import { getExpiry } from "@/services/api";
import type { WsTick, WsInstrument, WsMode } from "@/types/api";

const INDEX_INSTRUMENTS: WsInstrument[] = [
  { symbol: "NIFTY", exchange: "NSE_INDEX" },
  { symbol: "BANKNIFTY", exchange: "NSE_INDEX" },
  { symbol: "SENSEX", exchange: "BSE_INDEX" },
  { symbol: "INDIAVIX", exchange: "NSE_INDEX" },
  // Rendered by the Index Strip and the Market Overview indices tab. Both
  // showed a permanently "Awaiting tick" card until they were subscribed here.
  { symbol: "FINNIFTY", exchange: "NSE_INDEX" },
  { symbol: "NIFTYIT", exchange: "NSE_INDEX" },
];

/** MCX commodities that need nearest-futures resolution */
const MCX_COMMODITIES = ["GOLD", "SILVER", "CRUDEOIL", "NATURALGAS"] as const;

/**
 * Convert expiry "02-APR-26" to symbol suffix "02APR26FUT"
 */
function expiryToSuffix(expiry: string): string {
  return expiry.replace(/-/g, "").toUpperCase() + "FUT";
}

/**
 * Resolve each MCX commodity to its nearest futures contract symbol.
 * Returns a map: display name → full symbol (e.g. "GOLD" → "GOLD02APR26FUT")
 */
async function resolveMcxFutures(): Promise<Map<string, string>> {
  const map = new Map<string, string>();
  const results = await Promise.allSettled(
    MCX_COMMODITIES.map(async (name) => {
      const resp = await getExpiry(name, "MCX", "futures");
      const expiries = Array.isArray(resp) ? resp : (resp as { expiry: string[] }).expiry ?? [];
      if (expiries.length > 0) {
        map.set(name, name + expiryToSuffix(expiries[0]));
      }
    })
  );
  // Log failures but don't block
  results.forEach((r, i) => {
    if (r.status === "rejected") {
      console.warn(`MCX expiry lookup failed for ${MCX_COMMODITIES[i]}:`, r.reason);
    }
  });
  return map;
}

/**
 * Declare a tick interest for one instrument.
 *
 * Any widget that reads live LTP from `tickAtomFamily` MUST hold a tick
 * interest for its instrument (directly or via a launcher that sets
 * `selectedSymbolAtom`), otherwise the atom never receives data. This hook is
 * the standard way to declare that interest — no per-widget socket code:
 *
 *   useTickSubscription(symbol, exchange);           // LTP stream
 *   useTickSubscription(symbol, exchange, "quote");  // full quote stream
 *
 * The WebSocket service reference-counts subscriptions, so many widgets can
 * declare the same instrument and the wire unsubscribe only fires when the
 * last one unmounts. Ticks arrive in `tickAtomFamily("{exchange}:{symbol}")`
 * via the useWsBridge tick pipeline (mounted once in AppLayout).
 *
 * Passing a null/undefined/empty symbol or exchange is a no-op, so callers
 * can gate the subscription on their own readiness state.
 */
export function useTickSubscription(
  symbol: string | null | undefined,
  exchange: string | null | undefined,
  mode: WsMode = "ltp",
): void {
  const wsUrl = useConnectionStore((s) => s.wsUrl);
  const apiKey = useConnectionStore((s) => s.apiKey);

  useEffect(() => {
    if (!wsUrl || !symbol || !exchange) return;
    const ws = getWsService(wsUrl, apiKey);
    if (!ws) return;
    const instrument: WsInstrument = { symbol, exchange };
    // Reference-counted: safe even when another widget already streams this
    // instrument. While disconnected the service buffers the wire message and
    // replays it after (re)connect, so declaring interest early is safe too.
    ws.subscribe([instrument], mode);
    return () => {
      ws.unsubscribe([instrument], mode);
    };
  }, [wsUrl, apiKey, symbol, exchange, mode]);
}

export function useWsBridge(enabled = true): void {
  const setWsConnected = useConnectionStore((s) => s.setWsConnected);
  const setWsFailure = useConnectionStore((s) => s.setWsFailure);
  const apiKey = useConnectionStore((s) => s.apiKey);
  const wsUrl = useConnectionStore((s) => s.wsUrl);
  const store = useStore();

  // Keep a live tick subscription for the instrument on EVERY FDC3 user
  // channel (the red channel is the legacy terminal-wide selection — set by
  // a watchlist row click, quick trade, etc.). Consumers that read
  // `tickAtomFamily` for a channel's instrument — OrderPad fund-mode sizing,
  // OrderLadder's shared-atom fallback, the command palette — depend on
  // this; without it their atoms stay permanently null for non-index
  // symbols. The WS service ref-counts subscriptions, so two channels on
  // the same instrument are safe. Implemented with store.sub (not
  // useAtomValue) so channel changes do not re-render the app shell that
  // mounts this bridge.
  useEffect(() => {
    if (!enabled || !wsUrl || !apiKey) return;
    const ws = getWsService(wsUrl, apiKey);
    if (!ws) return;

    const current = new Map<UserChannelId, WsInstrument>();
    const applyChannel = (channelId: UserChannelId) => {
      const next = store.get(channelInstrumentAtoms[channelId]);
      const previous = current.get(channelId);
      if (
        previous &&
        next &&
        previous.symbol === next.symbol &&
        previous.exchange === next.exchange
      ) {
        return;
      }
      if (previous) {
        ws.unsubscribe([previous], "ltp");
        current.delete(channelId);
      }
      if (next) {
        const instrument: WsInstrument = { symbol: next.symbol, exchange: next.exchange };
        current.set(channelId, instrument);
        ws.subscribe([instrument], "ltp");
      }
    };

    const unsubs = USER_CHANNELS.map((channel) => {
      applyChannel(channel.id);
      return store.sub(channelInstrumentAtoms[channel.id], () => applyChannel(channel.id));
    });
    return () => {
      unsubs.forEach((unsub) => unsub());
      current.forEach((instrument) => ws.unsubscribe([instrument], "ltp"));
      current.clear();
    };
  }, [enabled, store, apiKey, wsUrl]);

  useEffect(() => {
    if (!enabled || !wsUrl || !apiKey) {
      setWsConnected(false);
      setWsFailure(null);
      return;
    }
    const ws = getWsService(wsUrl, apiKey);
    if (!ws) return;

    // Map of resolved futures symbol → display name for tick routing
    // e.g. "MCX:GOLD02APR26FUT" → "MCX:GOLD"
    let futuresMap = new Map<string, string>();

    // --- RAF tick batching ---
    // During market hours multiple ticks may arrive before the browser paints
    // the next frame. Accumulate them in a Map (keyed by display key so each
    // instrument is written at most once per frame) and flush in rAF.
    const pendingTicks = new Map<string, WsTick>();
    let rafId: number | null = null;

    const unsubTick = ws.onTick((tick: WsTick) => {
      const key = `${tick.exchange}:${tick.symbol}`;
      // Route MCX futures ticks to their display-name atoms
      const displayKey = futuresMap.get(key) ?? key;
      // Preserve prevClose from the existing atom — WebSocket LTP mode does not
      // send close/prevClose, so a raw tick write would erase the REST-fetched
      // prevClose that usePrevClose merged in on mount.
      const existing = store.get(tickAtomFamily(displayKey));
      const merged: WsTick =
        existing?.prevClose != null
          ? { ...tick, prevClose: existing.prevClose }
          : tick;
      pendingTicks.set(displayKey, merged);
      if (rafId === null) {
        rafId = requestAnimationFrame(() => {
          for (const [k, t] of pendingTicks) {
            store.set(tickAtomFamily(k), t);
          }
          pendingTicks.clear();
          rafId = null;
        });
      }
    });

    const unsubStatus = ws.onStatus((connected: boolean) => {
      setWsConnected(connected);
      if (connected) {
        // Subscribe to equity indices immediately
        ws.subscribe(INDEX_INSTRUMENTS, "ltp");

        // Resolve MCX futures then subscribe
        resolveMcxFutures().then((mcxMap) => {
          const mcxInstruments: WsInstrument[] = [];
          for (const [displayName, futSymbol] of mcxMap) {
            mcxInstruments.push({ symbol: futSymbol, exchange: "MCX" });
            futuresMap.set(`MCX:${futSymbol}`, `MCX:${displayName}`);
          }
          if (mcxInstruments.length > 0) {
            ws.subscribe(mcxInstruments, "ltp");
          }
        });
      }
    });

    // Mirror the service's failure state (auth rejection, transport drop)
    // into the connection store so the status chrome can explain WHY the
    // socket is down instead of a bare "Disconnected".
    const unsubFailure = ws.onFailure(setWsFailure);
    // Seed with the current value — the service may have latched an auth
    // failure before this hook (re)mounted.
    setWsFailure(ws.failure);

    ws.connect();

    return () => {
      // Cancel any pending RAF flush so stale ticks are not written after
      // the hook unmounts (e.g. during HMR or navigation away from /trade).
      if (rafId !== null) {
        cancelAnimationFrame(rafId);
        rafId = null;
      }
      pendingTicks.clear();
      unsubTick();
      unsubStatus();
      unsubFailure();
      ws.disconnect();
    };
  }, [enabled, setWsConnected, setWsFailure, store, apiKey, wsUrl]);
}
