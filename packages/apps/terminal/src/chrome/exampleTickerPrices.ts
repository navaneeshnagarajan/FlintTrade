/**
 * Example tape prices share the chart's explore snapshot.
 *
 * The chart paints `makeMockHistory` from `mockDataEngine.getSnapshot()` as
 * soon as Example mode loads. The ticker atoms wait for the demo feed's first
 * interval, so the tape can read "NIFTY 50 —" beside candles that already
 * have those prices. This fill is Example-only: Practice and Live keep an
 * empty tape rather than presenting sample prices as a broker quote.
 */

import { mockDataEngine } from "@/services/mockDataEngine";
import type { WsTick } from "@/types/api";

const EXAMPLE_TICKER_SYMBOLS: Record<string, string> = {
  "NIFTY 50": "NIFTY",
  SENSEX: "SENSEX",
  "BANK NIFTY": "BANKNIFTY",
  VIX: "INDIAVIX",
  GOLD: "GOLD",
  SILVER: "SILVER",
  CRUDEOIL: "CRUDEOIL",
  NATGAS: "NATURALGAS",
};

export function exampleTickerTick(name: string): WsTick | null {
  const symbol = EXAMPLE_TICKER_SYMBOLS[name];
  if (!symbol) return null;
  const tick = mockDataEngine.getSnapshot().find((row) => row.symbol === symbol);
  if (!tick || !(tick.ltp > 0)) return null;
  return {
    symbol: tick.symbol,
    exchange: tick.exchange,
    ltp: tick.ltp,
    open: tick.open,
    high: tick.high,
    low: tick.low,
    close: tick.close,
    prevClose: tick.close,
    volume: tick.volume,
    change: tick.change,
    pct: tick.changePct,
  };
}

export function withExampleTickerPrices<T extends { name: string; data: WsTick | null }>(
  symbols: T[],
  example: boolean,
): T[] {
  if (!example) return symbols;
  return symbols.map((symbol) => {
    if (symbol.data?.ltp != null && symbol.data.ltp > 0) return symbol;
    const tick = exampleTickerTick(symbol.name);
    return tick ? { ...symbol, data: tick } : symbol;
  });
}
