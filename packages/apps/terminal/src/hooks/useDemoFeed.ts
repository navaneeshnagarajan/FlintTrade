/**
 * useDemoFeed — drives the simulated-live market feed for Explore/Demo mode.
 *
 * In Explore mode there is no broker WebSocket, so the market atoms would
 * otherwise sit on a static snapshot. This hook starts the self-contained
 * {@link mockDataEngine} (a bounded random walk over a handful of Indian
 * instruments) and writes each simulated tick into the SAME Jotai market atoms
 * the real WS bridge feeds — so LTP displays, the ticker, and atom-driven
 * widgets visibly "tick" like live data while the operator is exploring.
 *
 * Strictly gated to `mode === "explore"`. It never runs in Practice or Live, so
 * no simulated price can reach a real-money surface.
 */

import { useEffect } from "react";
import { useStore } from "jotai";
import { tickAtomFamily } from "@/atoms/marketAtoms";
import { useModeStore } from "@/stores/modeStore";
import { mockDataEngine } from "@/services/mockDataEngine";

export function useDemoFeed(): void {
  const isExplore = useModeStore((s) => s.mode === "explore");
  const store = useStore();

  useEffect(() => {
    if (!isExplore) return;

    const unsubscribe = mockDataEngine.onTick((ticks) => {
      for (const t of ticks) {
        store.set(tickAtomFamily(`${t.exchange}:${t.symbol}`), {
          symbol: t.symbol,
          exchange: t.exchange,
          ltp: t.ltp,
          open: t.open,
          high: t.high,
          low: t.low,
          close: t.close,
          volume: t.volume,
          change: t.change,
          pct: t.changePct,
          prevClose: t.close,
        });
      }
    });

    mockDataEngine.start(1000);

    return () => {
      unsubscribe();
      mockDataEngine.stop();
    };
  }, [isExplore, store]);
}
