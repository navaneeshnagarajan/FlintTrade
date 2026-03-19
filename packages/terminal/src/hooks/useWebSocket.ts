import { useEffect, useRef, useState } from "react";
import { getWsService } from "@/services/websocket";
import { useConnectionStore } from "@/stores/connectionStore";
import type { WsInstrument, WsTick, WsMode } from "@/types/api";

type TickMap = Record<string, WsTick>;

/**
 * React hook wrapping the WebSocket service.
 * Subscribe to instruments on mount, unsubscribe on unmount.
 * Returns the latest tick keyed by "exchange:symbol".
 */
export default function useWebSocket(
  instruments: WsInstrument[] = [],
  mode: WsMode = "ltp",
): { ticks: TickMap; connected: boolean } {
  const wsUrl                         = useConnectionStore((s) => s.wsUrl);
  const apiKey                        = useConnectionStore((s) => s.apiKey);
  const [ticks, setTicks]             = useState<TickMap>({});
  const [connected, setConnected]     = useState(false);
  const prevRef                       = useRef<WsInstrument[]>([]);

  // Subscribe to tick and status callbacks
  useEffect(() => {
    if (!wsUrl) return;
    const ws = getWsService(wsUrl, apiKey);
    if (!ws.isConnected) ws.connect();

    const unsubTick = ws.onTick((tick: WsTick) => {
      const key = `${tick.exchange}:${tick.symbol}`;
      setTicks((prev) => ({ ...prev, [key]: tick }));
    });
    const unsubStatus = ws.onStatus((c: boolean) => setConnected(c));
    setConnected(ws.isConnected);

    return () => {
      unsubTick();
      unsubStatus();
    };
  }, [wsUrl]);

  // Manage instrument subscriptions
  useEffect(() => {
    if (!wsUrl || instruments.length === 0) return;
    const ws = getWsService(wsUrl);

    const toAdd = instruments.filter(
      (i) => !prevRef.current.some((p) => p.symbol === i.symbol && p.exchange === i.exchange),
    );
    const toRemove = prevRef.current.filter(
      (p) => !instruments.some((i) => i.symbol === p.symbol && i.exchange === p.exchange),
    );

    if (toRemove.length) ws.unsubscribe(toRemove, mode);
    if (toAdd.length)    ws.subscribe(toAdd, mode);
    prevRef.current = instruments;

    return () => {
      if (prevRef.current.length) {
        ws.unsubscribe(prevRef.current, mode);
      }
      prevRef.current = [];
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [wsUrl, JSON.stringify(instruments), mode]);

  return { ticks, connected };
}
