import { useEffect } from "react";
import { useStore } from "jotai";
import { tickAtomFamily } from "@/atoms/marketAtoms";
import { useConnectionStore } from "@/stores/connectionStore";
import { getWsService } from "@/services/websocket";
import type { WsTick, WsInstrument } from "@/types/api";

const INDEX_INSTRUMENTS: WsInstrument[] = [
  { symbol: "NIFTY", exchange: "NSE_INDEX" },
  { symbol: "BANKNIFTY", exchange: "NSE_INDEX" },
  { symbol: "SENSEX", exchange: "BSE_INDEX" },
  { symbol: "INDIAVIX", exchange: "NSE_INDEX" },
];

export function useWsBridge(): void {
  const setWsConnected = useConnectionStore((s) => s.setWsConnected);
  const store = useStore();

  useEffect(() => {
    const { wsUrl, apiKey } = useConnectionStore.getState();
    if (!wsUrl) return;
    const ws = getWsService(wsUrl, apiKey);

    const unsubTick = ws.onTick((tick: WsTick) => {
      const key = `${tick.exchange}:${tick.symbol}`;
      store.set(tickAtomFamily(key), tick);
    });

    const unsubStatus = ws.onStatus((connected: boolean) => {
      setWsConnected(connected);
      // Subscribe to indices once connected (after auth completes)
      if (connected) {
        ws.subscribe(INDEX_INSTRUMENTS, "ltp");
      }
    });

    ws.connect();

    return () => {
      unsubTick();
      unsubStatus();
    };
  }, [setWsConnected, store]);
}
