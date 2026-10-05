import { useEffect, useMemo, useRef, useState } from "react";
import { getWsService } from "@/services/websocket";
import { requireCurrentMarketDataScope, useMarketDataScope } from "@/hooks/useDataScope";
import { useMarketObservationEpoch } from "@/hooks/useMarketObservationEpoch";
import type { WsInstrument, WsTick, WsMode } from "@/types/api";

type TickMap = Record<string, WsTick>;

/** Native polling notifications coalesced per animation frame for widget interests. */
export default function useWebSocket(
  instruments: WsInstrument[] = [],
  mode: WsMode = "ltp",
  enabled = true,
): { ticks: TickMap; connected: boolean } {
  const scope = useMarketDataScope();
  const { epoch, currentEpoch } = useMarketObservationEpoch();
  const instrumentsKey = JSON.stringify(instruments.map(({ symbol, exchange }) => [symbol, exchange]));
  const interests = useMemo(() => (JSON.parse(instrumentsKey) as Array<[string, string]>)
    .map(([symbol, exchange]) => ({ symbol, exchange })), [instrumentsKey]);
  const identity = JSON.stringify([scope, epoch, instrumentsKey, mode, enabled]);
  const currentIdentityRef = useRef(identity);
  currentIdentityRef.current = identity;
  const [state, setState] = useState<{ identity: string; ticks: TickMap }>({ identity, ticks: {} });

  useEffect(() => {
    let active = true;
    let pending: TickMap = {};
    let frame: number | null = null;
    setState({ identity, ticks: {} });
    if (!enabled || !interests.length) return;
    const registry = getWsService();
    const keys = new Set(interests.map(({ symbol, exchange }) => `${exchange}:${symbol}`));
    const current = () => {
      if (!active || currentEpoch.current !== epoch || currentIdentityRef.current !== identity) return false;
      try { requireCurrentMarketDataScope(scope); return true; } catch { return false; }
    };
    const unsubscribe = registry.onTick((tick) => {
      const key = `${tick.exchange}:${tick.symbol}`;
      if (!current() || !keys.has(key)) return;
      pending[key] = tick;
      if (frame !== null) return;
      frame = requestAnimationFrame(() => {
        frame = null;
        if (!current()) { pending = {}; return; }
        const batch = pending;
        pending = {};
        setState((previous) => current()
          ? { identity, ticks: { ...(previous.identity === identity ? previous.ticks : {}), ...batch } }
          : previous);
      });
    });
    registry.subscribe(interests, mode);
    return () => {
      active = false;
      pending = {};
      if (frame !== null) cancelAnimationFrame(frame);
      unsubscribe();
      registry.unsubscribe(interests, mode);
    };
  }, [scope, epoch, currentEpoch, identity, interests, enabled, mode]);

  return { ticks: state.identity === identity ? state.ticks : {}, connected: false };
}
