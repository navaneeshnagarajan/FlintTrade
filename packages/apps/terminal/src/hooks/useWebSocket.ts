import { useEffect, useMemo, useRef, useState } from "react";
import { getWsService } from "@/services/websocket";
import { useConnectionStore } from "@/stores/connectionStore";
import type { WsInstrument, WsTick, WsMode } from "@/types/api";

type TickMap = Record<string, WsTick>;

/**
 * Batch incoming ticks with requestAnimationFrame so we do at most one
 * setState per animation frame (~16ms) instead of one per tick at 160+ Hz.
 */
function useTickBatcher(): [
  TickMap,
  (key: string, tick: WsTick) => void,
] {
  const [ticks, setTicks] = useState<TickMap>({});
  const pendingRef = useRef<TickMap>({});
  const rafRef = useRef<number>(0);

  const pushTick = (key: string, tick: WsTick) => {
    pendingRef.current[key] = tick;
    if (!rafRef.current) {
      rafRef.current = requestAnimationFrame(() => {
        const batch = pendingRef.current;
        pendingRef.current = {};
        rafRef.current = 0;
        setTicks((prev) => ({ ...prev, ...batch }));
      });
    }
  };

  // Cancel any pending rAF on unmount to prevent stale setState calls.
  useEffect(() => {
    return () => {
      if (rafRef.current) {
        cancelAnimationFrame(rafRef.current);
        rafRef.current = 0;
      }
    };
  }, []);

  return [ticks, pushTick];
}

/**
 * React hook wrapping the WebSocket service.
 * Subscribe to instruments on mount, unsubscribe on unmount.
 * Returns the latest tick keyed by "exchange:symbol".
 */
export default function useWebSocket(
  instruments: WsInstrument[] = [],
  mode: WsMode = "ltp",
  enabled = true,
): { ticks: TickMap; connected: boolean } {
  const wsUrl                         = useConnectionStore((s) => s.wsUrl);
  const apiKey                        = useConnectionStore((s) => s.apiKey);
  const [ticks, pushTick]             = useTickBatcher();
  const [connected, setConnected]     = useState(false);
  const prevRef                       = useRef<WsInstrument[]>([]);

  // Stable string key derived from the instruments array — avoids serialising on
  // every render while still tracking meaningful changes (symbol + exchange pairs).
  const instrumentsKey = useMemo(
    () => instruments.map((i) => `${i.exchange}:${i.symbol}`).join(","),
    [instruments],
  );

  // Subscribe to tick and status callbacks
  useEffect(() => {
    if (!enabled || !wsUrl || !apiKey) {
      setConnected(false);
      return;
    }
    const ws = getWsService(wsUrl, apiKey);
    if (!ws) return;
    if (!ws.isConnected) ws.connect();

    const unsubTick = ws.onTick((tick: WsTick) => {
      const key = `${tick.exchange}:${tick.symbol}`;
      pushTick(key, tick);
    });
    const unsubStatus = ws.onStatus((c: boolean) => setConnected(c));
    setConnected(ws.isConnected);

    return () => {
      unsubTick();
      unsubStatus();
    };
  }, [enabled, wsUrl, apiKey]);

  // Manage instrument subscriptions
  useEffect(() => {
    if (!enabled || !wsUrl || !apiKey || instruments.length === 0) return;
    const ws = getWsService(wsUrl);
    if (!ws) return;

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
  }, [enabled, wsUrl, apiKey, instrumentsKey, mode]);

  return { ticks, connected };
}
