/**
 * useTape — live Time & Sales feed for one instrument (W3).
 *
 * Subscribes the instrument in quote mode directly on the WebSocket service
 * (bypassing the batched useWebSocket hook, which coalesces ticks and would
 * drop prints) and folds every tick through the pure tape logic in tape.ts.
 */

import { useEffect, useRef, useState } from "react";
import { getWsService } from "@/services/websocket";
import { useConnectionStore } from "@/stores/connectionStore";
import type { WsInstrument, WsTick } from "@/types/api";
import { foldTick, initialTapeState, pushPrint, type TapePrint } from "./tape";

export function useTape(instrument: WsInstrument | null, enabled: boolean): TapePrint[] {
  const wsUrl = useConnectionStore((s) => s.wsUrl);
  const apiKey = useConnectionStore((s) => s.apiKey);
  const [tape, setTape] = useState<TapePrint[]>([]);
  const stateRef = useRef(initialTapeState());

  useEffect(() => {
    // Reset the tape whenever the instrument changes.
    stateRef.current = initialTapeState();
    setTape([]);

    if (!enabled || !instrument || !wsUrl) return;

    const ws = getWsService(wsUrl, apiKey);
    if (!ws) return;
    if (!ws.isConnected) ws.connect();

    const unsubTick = ws.onTick((tick: WsTick) => {
      if (tick.symbol !== instrument.symbol || tick.exchange !== instrument.exchange) return;
      const { print, state } = foldTick(stateRef.current, tick, new Date());
      stateRef.current = state;
      if (print) setTape((prev) => pushPrint(prev, print));
    });

    ws.subscribe([instrument], "quote");

    return () => {
      unsubTick();
      ws.unsubscribe([instrument], "quote");
    };
  }, [enabled, instrument?.symbol, instrument?.exchange, wsUrl, apiKey]); // eslint-disable-line react-hooks/exhaustive-deps

  return tape;
}
