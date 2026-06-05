/**
 * journalAnalytics tests
 *
 * Pure function tests for Trade Journal analytics calculations.
 */

import { describe, it, expect } from "vitest";
import type { JournalTrade } from "@/services/ftApi";
import {
  computeAnalytics,
  computeWeeklyWinRate,
  computeMonthlyWinRate,
  computeAvgPnlPerTrade,
  computeDayPnl,
  getBestDays,
  getWorstDays,
  computeInstrumentPnl,
  computeHoldingTime,
  computeAllStreaks,
  getLongestWinStreak,
  getLongestLossStreak,
  computeRiskRewardDistribution,
} from "../journalAnalytics";

// ---------------------------------------------------------------------------
// Sample data factory
// ---------------------------------------------------------------------------

function makeTrade(overrides: Partial<JournalTrade> = {}): JournalTrade {
  return {
    timestamp: "2026-03-25T10:00:00.000Z",
    symbol: "NIFTY",
    exchange: "NSE_FO",
    action: "BUY",
    quantity: 50,
    price: 23000,
    pnl: 500,
    strategy: "Scalper",
    entry_price: 23000,
    exit_price: 23010,
    fees: 20,
    ...overrides,
  };
}

const SAMPLE_TRADES: JournalTrade[] = [
  // Monday 2026-03-23
  makeTrade({ timestamp: "2026-03-23T09:30:00.000Z", symbol: "NIFTY", pnl: 1200 }),
  makeTrade({ timestamp: "2026-03-23T10:30:00.000Z", symbol: "NIFTY", pnl: -400 }),
  // Tuesday 2026-03-24
  makeTrade({ timestamp: "2026-03-24T09:30:00.000Z", symbol: "BANKNIFTY", pnl: 800 }),
  makeTrade({ timestamp: "2026-03-24T11:00:00.000Z", symbol: "BANKNIFTY", pnl: 300 }),
  // Wednesday 2026-03-25
  makeTrade({ timestamp: "2026-03-25T09:30:00.000Z", symbol: "NIFTY", pnl: -600 }),
  makeTrade({ timestamp: "2026-03-25T10:00:00.000Z", symbol: "RELIANCE", pnl: 150 }),
  // Thursday 2026-03-26
  makeTrade({ timestamp: "2026-03-26T09:30:00.000Z", symbol: "NIFTY", pnl: -200 }),
  makeTrade({ timestamp: "2026-03-26T10:00:00.000Z", symbol: "NIFTY", pnl: -300 }),
  // Friday 2026-03-27
  makeTrade({ timestamp: "2026-03-27T09:30:00.000Z", symbol: "BANKNIFTY", pnl: 1500 }),
];

// ---------------------------------------------------------------------------
// computeAnalytics
// ---------------------------------------------------------------------------

describe("computeAnalytics", () => {
  it("returns zeroed analytics for empty trades", () => {
    const a = computeAnalytics([]);
    expect(a.totalTrades).toBe(0);
    expect(a.netPnl).toBe(0);
    expect(a.winRate).toBe(0);
    expect(a.wins).toBe(0);
    expect(a.losses).toBe(0);
    expect(a.streakType).toBe("none");
  });

  it("computes correct totals for sample trades", () => {
    const a = computeAnalytics(SAMPLE_TRADES);
    expect(a.totalTrades).toBe(9);
    expect(a.wins).toBe(5);
    expect(a.losses).toBe(4);
    expect(a.netPnl).toBe(1200 - 400 + 800 + 300 - 600 + 150 - 200 - 300 + 1500);
    expect(a.winRate).toBeCloseTo((5 / 9) * 100, 1);
  });

  it("computes correct best and worst trade", () => {
    const a = computeAnalytics(SAMPLE_TRADES);
    expect(a.bestTrade).toBe(1500);
    expect(a.worstTrade).toBe(-600);
  });

  it("computes profit factor correctly", () => {
    const a = computeAnalytics(SAMPLE_TRADES);
    const grossWin = 1200 + 800 + 300 + 150 + 1500;
    const grossLoss = 400 + 600 + 200 + 300;
    expect(a.profitFactor).toBeCloseTo(grossWin / grossLoss, 2);
  });

  it("skips trades with pnl === 0", () => {
    const trades = [
      makeTrade({ pnl: 0 }),
      makeTrade({ pnl: 100 }),
    ];
    const a = computeAnalytics(trades);
    expect(a.totalTrades).toBe(1);
  });

  it("excludes open legs (null P&L) instead of counting them as losses", () => {
    // Live manual fills are journalled with pnl=null until a round-trip closes
    // them. They must not be miscounted as losing trades.
    const trades: JournalTrade[] = [
      makeTrade({ pnl: 1000 }), // win
      makeTrade({ pnl: -400 }), // loss
      makeTrade({ pnl: null as unknown as number }), // open leg
      makeTrade({ pnl: null as unknown as number }), // open leg
    ];
    const a = computeAnalytics(trades);
    expect(a.totalTrades).toBe(2); // only the 2 realised trades
    expect(a.wins).toBe(1);
    expect(a.losses).toBe(1); // NOT 3
    expect(a.netPnl).toBe(600);
  });

  it("tracks current streak", () => {
    // Last trade is a win (BANKNIFTY +1500 on Friday)
    const a = computeAnalytics(SAMPLE_TRADES);
    expect(a.streakType).toBe("win");
    expect(a.currentStreak).toBe(1);
  });

  it("tracks loss streak at end", () => {
    const trades = [
      makeTrade({ timestamp: "2026-03-23T09:30:00Z", pnl: 500 }),
      makeTrade({ timestamp: "2026-03-24T09:30:00Z", pnl: -100 }),
      makeTrade({ timestamp: "2026-03-25T09:30:00Z", pnl: -200 }),
      makeTrade({ timestamp: "2026-03-26T09:30:00Z", pnl: -300 }),
    ];
    const a = computeAnalytics(trades);
    expect(a.streakType).toBe("loss");
    expect(a.currentStreak).toBe(3);
  });
});

// ---------------------------------------------------------------------------
// computeWeeklyWinRate
// ---------------------------------------------------------------------------

describe("computeWeeklyWinRate", () => {
  it("returns empty for no trades", () => {
    expect(computeWeeklyWinRate([])).toEqual([]);
  });

  it("groups trades by ISO week", () => {
    const result = computeWeeklyWinRate(SAMPLE_TRADES);
    expect(result.length).toBeGreaterThan(0);
    // All sample trades are in the same week (W13 of 2026)
    expect(result[0].total).toBe(9);
    expect(result[0].wins).toBe(5);
    expect(result[0].losses).toBe(4);
  });

  it("computes win rate correctly", () => {
    const result = computeWeeklyWinRate(SAMPLE_TRADES);
    expect(result[0].winRate).toBeCloseTo((5 / 9) * 100, 1);
  });
});

// ---------------------------------------------------------------------------
// computeMonthlyWinRate
// ---------------------------------------------------------------------------

describe("computeMonthlyWinRate", () => {
  it("returns empty for no trades", () => {
    expect(computeMonthlyWinRate([])).toEqual([]);
  });

  it("groups trades by month", () => {
    const result = computeMonthlyWinRate(SAMPLE_TRADES);
    expect(result.length).toBe(1);
    expect(result[0].month).toBe("2026-03");
    expect(result[0].total).toBe(9);
  });

  it("handles multiple months", () => {
    const trades = [
      makeTrade({ timestamp: "2026-02-15T09:30:00Z", pnl: 100 }),
      makeTrade({ timestamp: "2026-03-15T09:30:00Z", pnl: -50 }),
    ];
    const result = computeMonthlyWinRate(trades);
    expect(result.length).toBe(2);
    expect(result[0].month).toBe("2026-02");
    expect(result[1].month).toBe("2026-03");
  });
});

// ---------------------------------------------------------------------------
// computeAvgPnlPerTrade
// ---------------------------------------------------------------------------

describe("computeAvgPnlPerTrade", () => {
  it("returns 0 for no trades", () => {
    expect(computeAvgPnlPerTrade([])).toBe(0);
  });

  it("computes average correctly", () => {
    const trades = [
      makeTrade({ pnl: 100 }),
      makeTrade({ pnl: -50 }),
      makeTrade({ pnl: 200 }),
    ];
    expect(computeAvgPnlPerTrade(trades)).toBeCloseTo(250 / 3, 2);
  });

  it("ignores zero-pnl trades", () => {
    const trades = [
      makeTrade({ pnl: 100 }),
      makeTrade({ pnl: 0 }),
    ];
    expect(computeAvgPnlPerTrade(trades)).toBe(100);
  });
});

// ---------------------------------------------------------------------------
// computeDayPnl / getBestDays / getWorstDays
// ---------------------------------------------------------------------------

describe("computeDayPnl", () => {
  it("returns empty for no trades", () => {
    expect(computeDayPnl([])).toEqual([]);
  });

  it("aggregates P&L by date", () => {
    const days = computeDayPnl(SAMPLE_TRADES);
    // Monday: 1200 - 400 = 800
    const monday = days.find((d) => d.date === "2026-03-23");
    expect(monday).toBeDefined();
    expect(monday!.pnl).toBe(800);
    expect(monday!.tradeCount).toBe(2);
  });

  it("is sorted by date ascending", () => {
    const days = computeDayPnl(SAMPLE_TRADES);
    for (let i = 1; i < days.length; i++) {
      expect(days[i].date >= days[i - 1].date).toBe(true);
    }
  });
});

describe("getBestDays", () => {
  it("returns top N profitable days sorted desc", () => {
    const days = computeDayPnl(SAMPLE_TRADES);
    const best = getBestDays(days, 2);
    expect(best.length).toBe(2);
    expect(best[0].pnl).toBeGreaterThanOrEqual(best[1].pnl);
  });
});

describe("getWorstDays", () => {
  it("returns worst N days sorted asc", () => {
    const days = computeDayPnl(SAMPLE_TRADES);
    const worst = getWorstDays(days, 2);
    expect(worst.length).toBe(2);
    expect(worst[0].pnl).toBeLessThanOrEqual(worst[1].pnl);
  });
});

// ---------------------------------------------------------------------------
// computeInstrumentPnl
// ---------------------------------------------------------------------------

describe("computeInstrumentPnl", () => {
  it("returns empty for no trades", () => {
    expect(computeInstrumentPnl([])).toEqual([]);
  });

  it("groups by symbol and sorts by P&L desc", () => {
    const result = computeInstrumentPnl(SAMPLE_TRADES);
    expect(result.length).toBe(3); // NIFTY, BANKNIFTY, RELIANCE

    // BANKNIFTY: 800 + 300 + 1500 = 2600 (most profitable)
    expect(result[0].symbol).toBe("BANKNIFTY");
    expect(result[0].pnl).toBe(2600);
  });

  it("counts trades per symbol", () => {
    const result = computeInstrumentPnl(SAMPLE_TRADES);
    const nifty = result.find((r) => r.symbol === "NIFTY");
    expect(nifty).toBeDefined();
    expect(nifty!.trades).toBe(5); // 5 NIFTY trades
  });
});

// ---------------------------------------------------------------------------
// computeHoldingTime
// ---------------------------------------------------------------------------

describe("computeHoldingTime", () => {
  it("returns zeros for no trades", () => {
    const stats = computeHoldingTime([]);
    expect(stats.avgMinutes).toBe(0);
    expect(stats.medianMinutes).toBe(0);
  });

  it("computes holding time from same-symbol same-day pairs", () => {
    const trades = [
      makeTrade({
        timestamp: "2026-03-25T09:30:00.000Z",
        symbol: "NIFTY",
        pnl: 100,
      }),
      makeTrade({
        timestamp: "2026-03-25T10:00:00.000Z",
        symbol: "NIFTY",
        pnl: -50,
      }),
    ];
    const stats = computeHoldingTime(trades);
    expect(stats.avgMinutes).toBe(30); // 30 minutes between 9:30 and 10:00
    expect(stats.medianMinutes).toBe(30);
  });

  it("returns zeros when all trades are solo (no pairs)", () => {
    const trades = [
      makeTrade({
        timestamp: "2026-03-25T09:30:00.000Z",
        symbol: "NIFTY",
        pnl: 100,
      }),
      makeTrade({
        timestamp: "2026-03-26T09:30:00.000Z",
        symbol: "BANKNIFTY",
        pnl: -50,
      }),
    ];
    const stats = computeHoldingTime(trades);
    expect(stats.avgMinutes).toBe(0);
  });
});

// ---------------------------------------------------------------------------
// computeAllStreaks / getLongestWinStreak / getLongestLossStreak
// ---------------------------------------------------------------------------

describe("computeAllStreaks", () => {
  it("returns empty for no trades", () => {
    expect(computeAllStreaks([])).toEqual([]);
  });

  it("identifies alternating wins and losses", () => {
    const trades = [
      makeTrade({ timestamp: "2026-03-23T09:00:00Z", pnl: 100 }),
      makeTrade({ timestamp: "2026-03-23T10:00:00Z", pnl: 200 }),
      makeTrade({ timestamp: "2026-03-23T11:00:00Z", pnl: -50 }),
      makeTrade({ timestamp: "2026-03-23T12:00:00Z", pnl: 300 }),
    ];
    const streaks = computeAllStreaks(trades);
    expect(streaks).toEqual([
      { type: "win", length: 2 },
      { type: "loss", length: 1 },
      { type: "win", length: 1 },
    ]);
  });
});

describe("getLongestWinStreak", () => {
  it("returns 0 for no streaks", () => {
    expect(getLongestWinStreak([])).toBe(0);
  });

  it("finds longest win streak", () => {
    const trades = [
      makeTrade({ timestamp: "2026-03-23T09:00:00Z", pnl: 100 }),
      makeTrade({ timestamp: "2026-03-23T10:00:00Z", pnl: 200 }),
      makeTrade({ timestamp: "2026-03-23T11:00:00Z", pnl: 300 }),
      makeTrade({ timestamp: "2026-03-23T12:00:00Z", pnl: -50 }),
      makeTrade({ timestamp: "2026-03-23T13:00:00Z", pnl: 100 }),
    ];
    const streaks = computeAllStreaks(trades);
    expect(getLongestWinStreak(streaks)).toBe(3);
  });
});

describe("getLongestLossStreak", () => {
  it("finds longest loss streak", () => {
    const trades = [
      makeTrade({ timestamp: "2026-03-23T09:00:00Z", pnl: 100 }),
      makeTrade({ timestamp: "2026-03-23T10:00:00Z", pnl: -50 }),
      makeTrade({ timestamp: "2026-03-23T11:00:00Z", pnl: -80 }),
      makeTrade({ timestamp: "2026-03-23T12:00:00Z", pnl: -30 }),
      makeTrade({ timestamp: "2026-03-23T13:00:00Z", pnl: 200 }),
    ];
    const streaks = computeAllStreaks(trades);
    expect(getLongestLossStreak(streaks)).toBe(3);
  });
});

// ---------------------------------------------------------------------------
// computeRiskRewardDistribution
// ---------------------------------------------------------------------------

describe("computeRiskRewardDistribution", () => {
  it("returns empty when no losses (cannot compute R)", () => {
    const trades = [
      makeTrade({ pnl: 100 }),
      makeTrade({ pnl: 200 }),
    ];
    expect(computeRiskRewardDistribution(trades)).toEqual([]);
  });

  it("returns empty for no trades", () => {
    expect(computeRiskRewardDistribution([])).toEqual([]);
  });

  it("distributes wins into correct buckets", () => {
    // Average loss = 100 (1R = 100)
    const trades = [
      makeTrade({ pnl: -100 }), // loss = 100
      makeTrade({ pnl: 50 }),   // 0.5R -> bucket "0-0.5R" (0.5 exactly goes to 0.5-1R)
      makeTrade({ pnl: 100 }),  // 1R -> bucket "1-1.5R"
      makeTrade({ pnl: 250 }),  // 2.5R -> bucket "2.5-3R"
      makeTrade({ pnl: 400 }),  // 4R -> bucket "3R+"
    ];
    const buckets = computeRiskRewardDistribution(trades);
    expect(buckets.length).toBe(7);

    const findBucket = (label: string) => buckets.find((b) => b.label === label);
    expect(findBucket("0.5-1R")!.count).toBe(1);  // 50/100 = 0.5 -> boundary goes to 0.5-1R (>= 0.5)
    expect(findBucket("1-1.5R")!.count).toBe(1);   // 100/100 = 1.0
    expect(findBucket("2.5-3R")!.count).toBe(1);   // 250/100 = 2.5
    expect(findBucket("3R+")!.count).toBe(1);       // 400/100 = 4.0
  });

  it("handles bucket boundary at 0.5", () => {
    // Average loss = 100
    const trades = [
      makeTrade({ pnl: -100 }),
      makeTrade({ pnl: 50 }),  // 0.5R — boundary, goes to 0.5-1R bucket (>= 0.5 && < 1)
    ];
    const buckets = computeRiskRewardDistribution(trades);
    const half = buckets.find((b) => b.label === "0.5-1R");
    expect(half!.count).toBe(1);
  });
});
