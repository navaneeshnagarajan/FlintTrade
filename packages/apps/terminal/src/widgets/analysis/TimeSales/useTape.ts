/** Infer individual prints from admitted native quote notifications. */
import { useEffect, useRef, useState } from "react";
import { getWsService } from "@/services/websocket";
import { requireCurrentMarketDataScope, useMarketDataScope } from "@/hooks/useDataScope";
import { useMarketObservationEpoch } from "@/hooks/useMarketObservationEpoch";
import type { WsInstrument } from "@/types/api";
import { foldTick, initialTapeState, pushPrint, type TapePrint } from "./tape";

export function useTape(instrument: WsInstrument | null, enabled: boolean): TapePrint[] {
  const scope = useMarketDataScope();
  const { epoch, currentEpoch } = useMarketObservationEpoch();
  const symbol = instrument?.symbol;
  const exchange = instrument?.exchange;
  const identity = JSON.stringify([scope, epoch, symbol, exchange, enabled]);
  const currentIdentityRef = useRef(identity);
  currentIdentityRef.current = identity;
  const [observation, setObservation] = useState<{ identity: string; prints: TapePrint[] }>({ identity, prints: [] });

  useEffect(() => {
    let active = true;
    // Each effect owns its fold baseline: A's cumulative volume and aggressor
    // side cannot produce a B print, even after a late callback or StrictMode replay.
    let foldState = initialTapeState();
    setObservation({ identity, prints: [] });
    if (!enabled || !symbol || !exchange) return;
    const interest = { symbol, exchange };
    const registry = getWsService();
    const current = () => {
      if (!active || currentEpoch.current !== epoch || currentIdentityRef.current !== identity) return false;
      try { requireCurrentMarketDataScope(scope); return true; } catch { return false; }
    };
    const unsubscribe = registry.onTick((tick) => {
      if (!current() || tick.symbol !== symbol || tick.exchange !== exchange) return;
      const folded = foldTick(foldState, tick, new Date());
      foldState = folded.state;
      if (!folded.print) return;
      const print = folded.print;
      setObservation((previous) => current()
        ? { identity, prints: pushPrint(previous.identity === identity ? previous.prints : [], print) }
        : previous);
    });
    registry.subscribe([interest], "quote");
    return () => {
      active = false;
      foldState = initialTapeState();
      unsubscribe();
      registry.unsubscribe([interest], "quote");
    };
  }, [scope, epoch, currentEpoch, identity, enabled, symbol, exchange]);

  return observation.identity === identity ? observation.prints : [];
}
