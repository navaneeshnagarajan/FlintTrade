import { describe, expect, it, vi } from "vitest";

import {
  ohlcvCacheKey,
  readOhlcvCache,
  writeOhlcvCache,
} from "@/lib/chartCache";

const BARS = [
  { timestamp: 1, open: 100, high: 105, low: 98, close: 103, volume: 10 },
];

function memoryStorage() {
  const values = new Map<string, string>();
  return {
    getItem: vi.fn((key: string) => values.get(key) ?? null),
    setItem: vi.fn((key: string, value: string) => { values.set(key, value); }),
    values,
  };
}

describe("OHLCV cache provenance", () => {
  it("uses distinct keys for Explore, Practice, and Live", () => {
    const args = ["NIFTY", "NSE_INDEX", "5m"] as const;
    expect(new Set([
      ohlcvCacheKey("explore:mock", ...args),
      ohlcvCacheKey("practice:sandbox:default", ...args),
      ohlcvCacheKey("live:openalgo:default", ...args),
    ]).size).toBe(3);
  });

  it("reads only a payload whose embedded provenance matches", () => {
    const storage = memoryStorage();
    writeOhlcvCache(storage, "explore:mock", "NIFTY", "NSE_INDEX", "5m", BARS, 123);

    expect(readOhlcvCache(storage, "explore:mock", "NIFTY", "NSE_INDEX", "5m")).toEqual({
      data: BARS,
      timestamp: 123,
      scope: "explore:mock",
    });
    expect(readOhlcvCache(storage, "live:openalgo:default", "NIFTY", "NSE_INDEX", "5m")).toBeNull();
  });

  it("rejects a mismatched or legacy unscoped payload even under the requested key", () => {
    const storage = memoryStorage();
    const key = ohlcvCacheKey("live:openalgo:default", "NIFTY", "NSE_INDEX", "5m");
    storage.values.set(key, JSON.stringify({ data: BARS, timestamp: 123, scope: "explore:mock" }));
    expect(readOhlcvCache(storage, "live:openalgo:default", "NIFTY", "NSE_INDEX", "5m")).toBeNull();

    storage.values.set(key, JSON.stringify({ data: BARS, timestamp: 123 }));
    expect(readOhlcvCache(storage, "live:openalgo:default", "NIFTY", "NSE_INDEX", "5m")).toBeNull();
  });
});
