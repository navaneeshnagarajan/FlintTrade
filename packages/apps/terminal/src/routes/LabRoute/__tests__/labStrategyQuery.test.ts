/**
 * labStrategyQuery.test.ts
 *
 * Pins the Strategy Lab `?strategy=` hydrate helpers used by AI Deploy
 * (`/lab?strategy=TrendEMACrossover`) and any other deep link that names a
 * registry key. The helpers must stay generic — not a one-name special case.
 */

import { describe, expect, it } from "vitest";
import type { StrategyInfo } from "@/services/ftApi";
import {
  mergeQueryStrategy,
  readStrategyQuery,
  resolveSelectedStrategy,
} from "../labStrategyQuery";

const SMA: StrategyInfo = {
  name: "sma_crossover",
  description: "Simple moving average crossover starter strategy",
  category: "Trend",
  parameters: [],
};

const TREND_EMA: StrategyInfo = {
  name: "TrendEMACrossover",
  description: "EMA crossover with confirmation",
  category: "Trend",
  parameters: [],
};

describe("readStrategyQuery", () => {
  it("returns a trimmed registry key", () => {
    expect(readStrategyQuery("TrendEMACrossover")).toBe("TrendEMACrossover");
    expect(readStrategyQuery("  RSIMomentum  ")).toBe("RSIMomentum");
  });

  it("rejects empty, blank, and unsafe values", () => {
    expect(readStrategyQuery(null)).toBeNull();
    expect(readStrategyQuery(undefined)).toBeNull();
    expect(readStrategyQuery("")).toBeNull();
    expect(readStrategyQuery("   ")).toBeNull();
    expect(readStrategyQuery("../evil")).toBeNull();
    expect(readStrategyQuery("Trend EMA Crossover")).toBeNull();
  });
});

describe("resolveSelectedStrategy", () => {
  it("uses the query key when the catalogue has not loaded yet", () => {
    expect(resolveSelectedStrategy("TrendEMACrossover", [])).toBe("TrendEMACrossover");
  });

  it("prefers the catalogue spelling when the query matches case-insensitively", () => {
    expect(resolveSelectedStrategy("trendemacrossover", [TREND_EMA, SMA])).toBe(
      "TrendEMACrossover",
    );
  });

  it("returns empty when there is no query", () => {
    expect(resolveSelectedStrategy(null, [SMA])).toBe("");
  });
});

describe("mergeQueryStrategy", () => {
  it("leaves the catalogue unchanged when the query is already listed", () => {
    expect(mergeQueryStrategy([TREND_EMA, SMA], "TrendEMACrossover")).toEqual([
      TREND_EMA,
      SMA,
    ]);
  });

  it("appends a linked entry so AI Deploy keys appear even in the demo catalogue", () => {
    const merged = mergeQueryStrategy([SMA], "TrendEMACrossover");
    expect(merged.map((s) => s.name)).toEqual(["sma_crossover", "TrendEMACrossover"]);
    expect(merged[1]).toMatchObject({
      name: "TrendEMACrossover",
      category: "Linked",
    });
  });

  it("does not invent an entry for an empty or unsafe query", () => {
    expect(mergeQueryStrategy([SMA], null)).toEqual([SMA]);
    expect(mergeQueryStrategy([SMA], "../evil")).toEqual([SMA]);
  });
});
