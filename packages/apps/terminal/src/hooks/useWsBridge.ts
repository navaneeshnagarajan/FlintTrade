import { useEffect } from "react";
import { useStore } from "jotai";
import { channelInstrumentAtoms, USER_CHANNELS, type UserChannelId } from "@/services/fdc3/channels";
import { getWsService } from "@/services/websocket";
import { getExpiry } from "@/services/api";
import type { WsInstrument, WsMode } from "@/types/api";

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
 * the standard way to declare that interest for the native REST polling feed:
 *
 *   useTickSubscription(symbol, exchange);           // last-traded price
 *   useTickSubscription(symbol, exchange, "quote");  // full quote
 *
 * The local interest registry reference-counts each instrument and mode, so
 * it remains available to the polling feed until the last interested widget
 * unmounts. Account-scoped polling publishes accepted results to
 * `tickAtomFamily("{exchange}:{symbol}")` in AppLayout.
 *
 * Passing a null/undefined/empty symbol or exchange is a no-op, so callers
 * can gate the subscription on their own readiness state.
 */
export function useTickSubscription(
  symbol: string | null | undefined,
  exchange: string | null | undefined,
  mode: WsMode = "ltp",
): void {

  useEffect(() => {
    if (!symbol || !exchange) return;
    const ws = getWsService();
    if (!ws) return;
    const instrument: WsInstrument = { symbol, exchange };
    // Declaring local interest performs no network operation. The account
    // readiness and publication fences belong to the polling feed.
    ws.subscribe([instrument], mode);
    return () => {
      ws.unsubscribe([instrument], mode);
    };
  }, [symbol, exchange, mode]);
}

/** Registers global and channel interests for the native polling feed. */
export function useWsBridge(enabled = true): void {
  const store = useStore();
  useEffect(() => {
    if (!enabled) return;
    const feed = getWsService();
    feed.subscribe(INDEX_INSTRUMENTS, "ltp");
    const current = new Map<UserChannelId, WsInstrument>();
    const applyChannel = (channelId: UserChannelId) => {
      const next = store.get(channelInstrumentAtoms[channelId]);
      const previous = current.get(channelId);
      if (previous?.symbol === next?.symbol && previous?.exchange === next?.exchange) return;
      if (previous) feed.unsubscribe([previous], "ltp");
      current.delete(channelId);
      if (next) { current.set(channelId, next); feed.subscribe([next], "ltp"); }
    };
    const unsubs = USER_CHANNELS.map((channel) => {
      applyChannel(channel.id);
      return store.sub(channelInstrumentAtoms[channel.id], () => applyChannel(channel.id));
    });
    let retired = false;
    let futures: WsInstrument[] = [];
    void resolveMcxFutures().then((map) => {
      if (retired) return;
      futures = [...map.values()].map((symbol) => ({ symbol, exchange: "MCX" }));
      feed.subscribe(futures, "ltp");
    });
    return () => {
      retired = true;
      unsubs.forEach((unsub) => unsub());
      current.forEach((instrument) => feed.unsubscribe([instrument], "ltp"));
      feed.unsubscribe(INDEX_INSTRUMENTS, "ltp");
      feed.unsubscribe(futures, "ltp");
    };
  }, [enabled, store]);
}
