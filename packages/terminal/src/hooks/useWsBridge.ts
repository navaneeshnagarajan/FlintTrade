import { useEffect } from "react";
import { useStore } from "jotai";
import { tickAtomFamily } from "@/atoms/marketAtoms";
import { useConnectionStore } from "@/stores/connectionStore";
import { getWsService } from "@/services/websocket";
import { getExpiry } from "@/services/api";
import type { WsTick, WsInstrument } from "@/types/api";

const INDEX_INSTRUMENTS: WsInstrument[] = [
  { symbol: "NIFTY", exchange: "NSE_INDEX" },
  { symbol: "BANKNIFTY", exchange: "NSE_INDEX" },
  { symbol: "SENSEX", exchange: "BSE_INDEX" },
  { symbol: "INDIAVIX", exchange: "NSE_INDEX" },
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

export function useWsBridge(): void {
  const setWsConnected = useConnectionStore((s) => s.setWsConnected);
  const store = useStore();

  useEffect(() => {
    const { wsUrl, apiKey } = useConnectionStore.getState();
    if (!wsUrl) return;
    const ws = getWsService(wsUrl, apiKey);
    if (!ws) return;

    // Map of resolved futures symbol → display name for tick routing
    // e.g. "MCX:GOLD02APR26FUT" → "MCX:GOLD"
    let futuresMap = new Map<string, string>();

    const unsubTick = ws.onTick((tick: WsTick) => {
      const key = `${tick.exchange}:${tick.symbol}`;
      // Route MCX futures ticks to their display-name atoms
      const displayKey = futuresMap.get(key) ?? key;
      store.set(tickAtomFamily(displayKey), tick);
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

    ws.connect();

    return () => {
      unsubTick();
      unsubStatus();
    };
  }, [setWsConnected, store]);
}
