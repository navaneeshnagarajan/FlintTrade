/**
 * Sample funding rate data for explore/disconnected mode.
 * Contains illustrative Delta Exchange perpetual funding rates.
 * Positive rate = longs pay shorts; negative = shorts pay longs.
 */

import type { FundingRatesResponse } from "@/services/ftApi";

/** Sample rows have no trustworthy schedule timestamp. */
const SAMPLE_NEXT_FUNDING_MS = 0;

/** Generate 7 days × 3 periods/day = 21 historical entries with realistic variation. */
function genHistory(base: number, volatility: number): number[] {
  const result: number[] = [];
  let current = base;
  for (let i = 0; i < 21; i++) {
    const shock = (Math.random() - 0.5) * volatility;
    current = Math.max(-0.002, Math.min(0.002, current + shock));
    result.push(parseFloat(current.toFixed(6)));
  }
  return result;
}

export const SAMPLE_FUNDING_RATES: FundingRatesResponse = {
  rates: [
    {
      symbol: "BTCUSD",
      rate: 0.0001,
      predicted_rate: 0.00012,
      next_funding_ms: SAMPLE_NEXT_FUNDING_MS,
      history: genHistory(0.0001, 0.00004),
      open_interest_usd: 4_280_000_000,
    },
    {
      symbol: "ETHUSD",
      rate: 0.00008,
      predicted_rate: 0.00009,
      next_funding_ms: SAMPLE_NEXT_FUNDING_MS,
      history: genHistory(0.00008, 0.00005),
      open_interest_usd: 1_640_000_000,
    },
    {
      symbol: "SOLUSD",
      rate: 0.00015,
      predicted_rate: 0.00014,
      next_funding_ms: SAMPLE_NEXT_FUNDING_MS,
      history: genHistory(0.00015, 0.00008),
      open_interest_usd: 380_000_000,
    },
    {
      symbol: "BNBUSD",
      rate: -0.00003,
      predicted_rate: -0.00002,
      next_funding_ms: SAMPLE_NEXT_FUNDING_MS,
      history: genHistory(-0.00003, 0.00006),
      open_interest_usd: 190_000_000,
    },
    {
      symbol: "XRPUSD",
      rate: 0.00005,
      predicted_rate: 0.00006,
      next_funding_ms: SAMPLE_NEXT_FUNDING_MS,
      history: genHistory(0.00005, 0.00007),
      open_interest_usd: 95_000_000,
    },
    {
      symbol: "MATICUSD",
      rate: -0.00007,
      predicted_rate: -0.00008,
      next_funding_ms: SAMPLE_NEXT_FUNDING_MS,
      history: genHistory(-0.00007, 0.00009),
      open_interest_usd: 42_000_000,
    },
    {
      symbol: "BTCINR",
      rate: 0.00009,
      predicted_rate: 0.0001,
      next_funding_ms: SAMPLE_NEXT_FUNDING_MS,
      history: genHistory(0.00009, 0.00005),
      open_interest_usd: 28_000_000,
    },
    {
      symbol: "ETHINR",
      rate: 0.00006,
      predicted_rate: 0.00007,
      next_funding_ms: SAMPLE_NEXT_FUNDING_MS,
      history: genHistory(0.00006, 0.00006),
      open_interest_usd: 12_000_000,
    },
    {
      symbol: "SOLINR",
      rate: 0.00012,
      predicted_rate: 0.00011,
      next_funding_ms: SAMPLE_NEXT_FUNDING_MS,
      history: genHistory(0.00012, 0.00007),
      open_interest_usd: 6_000_000,
    },
    {
      symbol: "XRPINR",
      rate: -0.00004,
      predicted_rate: -0.00003,
      next_funding_ms: SAMPLE_NEXT_FUNDING_MS,
      history: genHistory(-0.00004, 0.00008),
      open_interest_usd: 3_500_000,
    },
  ],
};
