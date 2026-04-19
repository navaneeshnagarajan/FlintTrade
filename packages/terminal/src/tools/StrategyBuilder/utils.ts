// Pure utility functions for StrategyBuilder — extracted from StrategyBuilderTool.tsx
// Absorbed patterns from openalgo-chart/src/services/strategyTemplates.js

import { formatCurrency as formatINRCanonical } from "@/lib/formatters";

import type { Leg, PayoffPoint, EquityPoint, PerfMetrics, Underlying } from "./types";

// Absorbed from strategyTemplates.js — calculateNetPremium
export function calculateNetPremium(legs: Leg[]): number {
  return legs.reduce((total, leg) => {
    const multiplier = leg.action === "BUY" ? 1 : -1;
    return total + multiplier * leg.lots * leg.premium;
  }, 0);
}

// Absorbed from strategyTemplates.js — validateStrategy
export function validateLegs(legs: Leg[]): { valid: boolean; error: string | null } {
  if (legs.length < 1) return { valid: false, error: "Add at least one leg" };
  if (legs.length > 6) return { valid: false, error: "Maximum 6 legs allowed" };
  for (let i = 0; i < legs.length; i++) {
    if (legs[i].strike <= 0)  return { valid: false, error: `Leg ${i + 1}: strike must be > 0` };
    if (legs[i].lots < 1)     return { valid: false, error: `Leg ${i + 1}: lots must be >= 1` };
    if (legs[i].premium < 0)  return { valid: false, error: `Leg ${i + 1}: premium must be >= 0` };
  }
  return { valid: true, error: null };
}

export function genId(): string {
  return `leg-${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;
}

export function formatINR(v: number): string {
  return formatINRCanonical(v);
}

export function computePayoff(legs: Leg[], spotPrice: number): PayoffPoint[] {
  const range = spotPrice * 0.15;
  const steps = 40;
  const step = (range * 2) / steps;
  const points: PayoffPoint[] = [];

  for (let i = 0; i <= steps; i++) {
    const price = spotPrice - range + i * step;
    let pnl = 0;
    for (const leg of legs) {
      const multiplier = leg.action === "BUY" ? 1 : -1;
      const intrinsic =
        leg.optionType === "CE"
          ? Math.max(0, price - leg.strike)
          : Math.max(0, leg.strike - price);
      pnl += multiplier * leg.lots * (intrinsic - leg.premium);
    }
    points.push({ price, pnl });
  }
  return points;
}

// SPAN margin estimate (simplified — absorbed from openalgo-chart PositionTracker margin concept)
// Use 15% of notional for sold options, 100% premium for bought
export function estimateMargin(legs: Leg[], underlying: Underlying): number {
  const notionalPerUnit = 20000; // approximate index unit value for NIFTY
  let margin = 0;
  for (const leg of legs) {
    if (leg.action === "SELL") {
      margin += 0.15 * notionalPerUnit * leg.lots * underlying.lotSize;
    } else {
      margin += leg.premium * leg.lots * underlying.lotSize;
    }
  }
  return margin;
}

// Equity curve computation from bar closes + signals
export function computeEquityCurve(
  bars: { close: number }[],
  signals: { bar: number; type: "BUY" | "SELL" }[],
): EquityPoint[] {
  let inTrade = false;
  let entryPrice = 0;
  let equity = 10000; // notional starting capital
  const curve: EquityPoint[] = [{ bar: 0, equity }];

  const signalMap = new Map(signals.map((s) => [s.bar, s.type]));

  for (let i = 1; i < bars.length; i++) {
    const sig = signalMap.get(i);
    if (sig === "BUY" && !inTrade) {
      inTrade = true;
      entryPrice = bars[i].close;
    } else if (sig === "SELL" && inTrade) {
      const pct = (bars[i].close - entryPrice) / entryPrice;
      equity *= 1 + pct;
      inTrade = false;
      curve.push({ bar: i, equity });
    }
  }

  // Close any open position at last bar
  if (inTrade && bars.length > 0) {
    const lastClose = bars[bars.length - 1].close;
    const pct = (lastClose - entryPrice) / entryPrice;
    equity *= 1 + pct;
    curve.push({ bar: bars.length - 1, equity });
  }

  return curve;
}

// Performance metrics
export function computeMetrics(
  bars: { close: number }[],
  signals: { bar: number; type: "BUY" | "SELL" }[],
): PerfMetrics {
  const buys  = signals.filter((s) => s.type === "BUY").length;
  const sells = signals.filter((s) => s.type === "SELL").length;

  let inTrade = false;
  let entryPrice = 0;
  const tradeReturns: number[] = [];
  const signalMap = new Map(signals.map((s) => [s.bar, s.type]));

  for (let i = 1; i < bars.length; i++) {
    const sig = signalMap.get(i);
    if (sig === "BUY" && !inTrade) {
      inTrade = true;
      entryPrice = bars[i].close;
    } else if (sig === "SELL" && inTrade) {
      tradeReturns.push((bars[i].close - entryPrice) / entryPrice);
      inTrade = false;
    }
  }

  const totalReturn =
    tradeReturns.length > 0
      ? tradeReturns.reduce((acc, r) => acc * (1 + r), 1) - 1
      : 0;

  const mean =
    tradeReturns.length > 0
      ? tradeReturns.reduce((a, b) => a + b, 0) / tradeReturns.length
      : 0;
  const variance =
    tradeReturns.length > 1
      ? tradeReturns.reduce((a, r) => a + (r - mean) ** 2, 0) / tradeReturns.length
      : 0;
  const stdDev = Math.sqrt(variance);
  const sharpeApprox = stdDev > 0 ? (mean / stdDev) * Math.sqrt(tradeReturns.length) : 0;

  return { totalReturn, totalSignals: signals.length, buySignals: buys, sellSignals: sells, sharpeApprox };
}
