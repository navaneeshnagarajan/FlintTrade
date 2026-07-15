import type { FlintChartOhlcvBar } from "@flinttrade/design-system";

import { ohlcvCacheSchema, safeParse } from "@/lib/safeParse";

type CacheStorage = Pick<Storage, "getItem" | "setItem">;

export function ohlcvCacheKey(
  scope: string,
  symbol: string,
  exchange: string,
  interval: string,
): string {
  return ["ft-chart-v2", scope, exchange, symbol, interval]
    .map(encodeURIComponent)
    .join(":");
}

export function readOhlcvCache(
  storage: CacheStorage,
  scope: string,
  symbol: string,
  exchange: string,
  interval: string,
) {
  const key = ohlcvCacheKey(scope, symbol, exchange, interval);
  const cached = safeParse(storage.getItem(key), ohlcvCacheSchema);
  return cached?.scope === scope ? cached : null;
}

export function writeOhlcvCache(
  storage: CacheStorage,
  scope: string,
  symbol: string,
  exchange: string,
  interval: string,
  data: FlintChartOhlcvBar[],
  timestamp = Date.now(),
): void {
  try {
    storage.setItem(
      ohlcvCacheKey(scope, symbol, exchange, interval),
      JSON.stringify({ data, timestamp, scope }),
    );
  } catch {
    // Storage can be unavailable or full; the network response still renders.
  }
}
