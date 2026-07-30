// Chart replay hook.
// Drives a setInterval ticker that feeds historical bars one at a time
// into the candlestick series, simulating a live replay of the session.
//
// Design decisions:
// - Speed multipliers map to concrete tick intervals (ms): 1x=500, 2x=250, 5x=100, 10x=50
// - The interval is rebuilt whenever speed or isReplaying changes
// - On mount the chart is populated with bars[0..replayIndex] so seeking works
// - Returning isReplaying=true is the gate ChartWidget uses to suppress WS ticks

import { useState, useEffect, useRef, useCallback } from "react";
import type { IChartApi, ISeriesApi, Time } from "lightweight-charts";
import type { FlintChartOhlcvBar as OhlcvBar } from "@flinttrade/design-system";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface ReplayState {
  isReplaying: boolean;
  replayIndex: number;
  replaySpeed: ReplaySpeed;
  totalBars: number;
}

export type ReplaySpeed = 1 | 2 | 5 | 10;

export interface UseChartReplayReturn extends ReplayState {
  isPlaying: boolean;
  play: () => void;
  pause: () => void;
  reset: () => void;
  exitReplay: () => void;
  seek: (index: number) => void;
  setSpeed: (speed: ReplaySpeed) => void;
  enterReplay: () => void;
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const SPEED_MS: Record<ReplaySpeed, number> = {
  1: 500,
  2: 250,
  5: 100,
  10: 50,
};

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

export function useChartReplay(
  chartRef: React.RefObject<IChartApi | null>,
  candleRef: React.RefObject<ISeriesApi<"Candlestick"> | null>,
  // Accept a ref so the hook always reads the live populated bars array rather
  // than stale snapshot values from the render cycle.
  barsRef: React.RefObject<OhlcvBar[]>,
): UseChartReplayReturn {
  const [isReplaying, setIsReplaying] = useState(false);
  const [isPlaying, setIsPlaying] = useState(false);
  const [replayIndex, setReplayIndex] = useState(0);
  const [replaySpeed, setReplaySpeed] = useState<ReplaySpeed>(1);

  // totalBars is derived from the ref length — used only for display/clamping
  // We expose a derived getter via state that is set whenever replay is entered
  const [totalBars, setTotalBars] = useState(0);

  // Stable ref so the interval callback always sees current index
  const indexRef = useRef(replayIndex);
  useEffect(() => { indexRef.current = replayIndex; }, [replayIndex]);

  // ---------------------------------------------------------------------------
  // Apply bars up to `index` onto the candle series (used on seek / enter)
  // ---------------------------------------------------------------------------
  const applyBarsUpTo = useCallback((toIndex: number) => {
    const candle = candleRef.current;
    const chart = chartRef.current;
    const allBars = barsRef.current;
    if (!candle || !chart || !allBars || allBars.length === 0) return;

    const slice = allBars.slice(0, toIndex + 1);
    const candles = slice.map((b) => ({
      time: b.timestamp as unknown as Time,
      open: b.open,
      high: b.high,
      low: b.low,
      close: b.close,
    }));
    candle.setData(candles);
    chart.timeScale().fitContent();
  }, [candleRef, chartRef, barsRef]);

  // ---------------------------------------------------------------------------
  // Replay ticker
  // ---------------------------------------------------------------------------
  useEffect(() => {
    if (!isReplaying || !isPlaying) return;

    const intervalMs = SPEED_MS[replaySpeed];
    const id = setInterval(() => {
      const allBars = barsRef.current;
      const candle = candleRef.current;
      if (!candle || !allBars || allBars.length === 0) return;

      const next = indexRef.current + 1;
      if (next >= allBars.length) {
        // Reached the end — pause at last bar
        setIsPlaying(false);
        return;
      }

      const bar = allBars[next];
      candle.update({
        time: bar.timestamp as unknown as Time,
        open: bar.open,
        high: bar.high,
        low: bar.low,
        close: bar.close,
      });
      indexRef.current = next;
      setReplayIndex(next);
    }, intervalMs);

    return () => clearInterval(id);
  }, [isReplaying, isPlaying, replaySpeed, candleRef, barsRef]);

  // ---------------------------------------------------------------------------
  // Controls
  // ---------------------------------------------------------------------------

  const enterReplay = useCallback(() => {
    const allBars = barsRef.current;
    if (!allBars || allBars.length === 0) return;
    const startIndex = 0;
    setTotalBars(allBars.length);
    setIsReplaying(true);
    setIsPlaying(false);
    setReplayIndex(startIndex);
    indexRef.current = startIndex;
    applyBarsUpTo(startIndex);
  }, [applyBarsUpTo, barsRef]);

  const play = useCallback(() => {
    if (!isReplaying) return;
    const allBars = barsRef.current;
    // If at the end, reset to start first
    if (!allBars || indexRef.current >= allBars.length - 1) {
      setReplayIndex(0);
      indexRef.current = 0;
      applyBarsUpTo(0);
    }
    setIsPlaying(true);
  }, [isReplaying, applyBarsUpTo, barsRef]);

  const pause = useCallback(() => {
    setIsPlaying(false);
  }, []);

  const reset = useCallback(() => {
    setIsPlaying(false);
    setReplayIndex(0);
    indexRef.current = 0;
    applyBarsUpTo(0);
  }, [applyBarsUpTo]);

  const seek = useCallback((index: number) => {
    const clamped = Math.max(0, Math.min(index, (barsRef.current?.length ?? 1) - 1));
    setIsPlaying(false);
    setReplayIndex(clamped);
    indexRef.current = clamped;
    applyBarsUpTo(clamped);
  }, [applyBarsUpTo, barsRef]);

  const exitReplay = useCallback(() => {
    setIsPlaying(false);
    setIsReplaying(false);
    setReplayIndex(0);
    indexRef.current = 0;
    // Caller (ChartWidget) will re-apply the full bars array when isReplaying
    // transitions to false — no need to touch the series here.
  }, []);

  const handleSetSpeed = useCallback((speed: ReplaySpeed) => {
    setReplaySpeed(speed);
  }, []);

  return {
    isReplaying,
    isPlaying,
    replayIndex,
    replaySpeed,
    totalBars,
    play,
    pause,
    reset,
    seek,
    exitReplay,
    enterReplay,
    setSpeed: handleSetSpeed,
  };
}
