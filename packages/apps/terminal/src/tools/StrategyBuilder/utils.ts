// Pure utility functions for StrategyBuilder — extracted from StrategyBuilderTool.tsx
// Adapted patterns from openalgo-chart/src/services/strategyTemplates.js

import { formatCurrency as formatINRCanonical } from "@/lib/formatters";

import type { Leg, PayoffPoint, EquityPoint, PerfMetrics, Underlying } from "./types";

// Adapted from strategyTemplates.js — calculateNetPremium
export function calculateNetPremium(legs: Leg[]): number {
  return legs.reduce((total, leg) => {
    const multiplier = leg.action === "BUY" ? 1 : -1;
    return total + multiplier * leg.lots * leg.premium;
  }, 0);
}

// Adapted from strategyTemplates.js — validateStrategy
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

/** Per-unit expiry P&L (lots included, contract lot-size not). */
export function pnlAtExpiry(legs: Leg[], price: number): number {
  let pnl = 0;
  for (const leg of legs) {
    const multiplier = leg.action === "BUY" ? 1 : -1;
    const intrinsic =
      leg.optionType === "CE"
        ? Math.max(0, price - leg.strike)
        : Math.max(0, leg.strike - price);
    pnl += multiplier * leg.lots * (intrinsic - leg.premium);
  }
  return pnl;
}

export interface PayoffSummary {
  /** +Infinity when the right-hand slope is positive (naked long calls, long straddles, …). */
  maxProfit: number;
  /** −Infinity when the right-hand slope is negative (naked short calls, short straddles, …). */
  maxLoss: number;
  breakevens: number[];
}

const PNL_EPS = 1e-9;

/** Net call exposure — the slope of expiry P&L as spot → +∞. */
function rightHandSlope(legs: Leg[]): number {
  return legs.reduce((acc, leg) => {
    if (leg.optionType !== "CE") return acc;
    return acc + (leg.action === "BUY" ? 1 : -1) * leg.lots;
  }, 0);
}

function uniqueStrikes(legs: Leg[]): number[] {
  return [...new Set(legs.map((leg) => leg.strike).filter((strike) => strike > 0))].sort(
    (a, b) => a - b,
  );
}

/**
 * Analytical expiry summary: evaluate kinks (spot 0 and every strike) and
 * inspect the right-hand slope instead of taking min/max of a sampled curve.
 *
 * A ±15% scan caps unbounded legs (FT-LAB-001: NIFTY 22,500 ATM long call
 * reported ₹2,53,125) and misses breakevens that sit on a flat-zero segment
 * (zero-premium long call never changes sign).
 */
export function computePayoffSummary(legs: Leg[]): PayoffSummary {
  if (legs.length === 0) {
    return { maxProfit: 0, maxLoss: 0, breakevens: [] };
  }

  const strikes = uniqueStrikes(legs);
  const nodes = [0, ...strikes];
  const pnls = nodes.map((price) => pnlAtExpiry(legs, price));
  const slope = rightHandSlope(legs);

  let maxProfit = -Infinity;
  let maxLoss = Infinity;
  for (const pnl of pnls) {
    if (pnl > maxProfit) maxProfit = pnl;
    if (pnl < maxLoss) maxLoss = pnl;
  }
  if (slope > PNL_EPS) maxProfit = Infinity;
  else if (slope < -PNL_EPS) maxLoss = -Infinity;

  return { maxProfit, maxLoss, breakevens: findBreakevens(nodes, pnls, slope) };
}

function findBreakevens(nodes: number[], pnls: number[], slope: number): number[] {
  const candidates: number[] = [];

  for (let i = 0; i < nodes.length - 1; i++) {
    const pa = pnls[i];
    const pb = pnls[i + 1];
    if ((pa < -PNL_EPS && pb > PNL_EPS) || (pa > PNL_EPS && pb < -PNL_EPS)) {
      candidates.push(nodes[i] + (-pa / (pb - pa)) * (nodes[i + 1] - nodes[i]));
    }
  }

  const last = nodes[nodes.length - 1];
  const pLast = pnls[pnls.length - 1];
  if (Math.abs(slope) > PNL_EPS) {
    const crossing = last - pLast / slope;
    if (crossing > last + PNL_EPS) candidates.push(crossing);
  }

  for (let i = 0; i < nodes.length; i++) {
    if (Math.abs(pnls[i]) > PNL_EPS) continue;
    const leftZero = i === 0 || Math.abs(pnls[i - 1]) <= PNL_EPS;
    const rightZero =
      i === nodes.length - 1
        ? Math.abs(slope) <= PNL_EPS
        : Math.abs(pnls[i + 1]) <= PNL_EPS;
    const leavesLeft = i > 0 && !leftZero;
    const leavesRight = !rightZero;
    if (leavesLeft || leavesRight) candidates.push(nodes[i]);
  }

  candidates.sort((a, b) => a - b);
  const deduped: number[] = [];
  for (const value of candidates) {
    if (deduped.length === 0 || Math.abs(value - deduped[deduped.length - 1]) > 1e-6) {
      deduped.push(value);
    }
  }
  return deduped;
}

export function computePayoff(legs: Leg[], spotPrice: number): PayoffPoint[] {
  const range = spotPrice * 0.15;
  const steps = 40;
  const step = (range * 2) / steps;
  const points: PayoffPoint[] = [];

  for (let i = 0; i <= steps; i++) {
    const price = spotPrice - range + i * step;
    points.push({ price, pnl: pnlAtExpiry(legs, price) });
  }
  return points;
}

// Rough SPAN-style margin estimate (simplified — adapted from openalgo-chart
// PositionTracker margin concept): ~15% of the leg's REAL notional for sold
// options, 100% of premium for bought. The notional derives from each leg's
// own strike × lot size — previously a hardcoded ₹20,000 "NIFTY unit value"
// was applied to every underlying, so a SENSEX (~80,000) collar and a
// MIDCPNIFTY one showed the same number.
export function estimateMargin(legs: Leg[], underlying: Underlying): number {
  let margin = 0;
  for (const leg of legs) {
    if (leg.action === "SELL") {
      const notionalPerLot = leg.strike * underlying.lotSize;
      margin += 0.15 * notionalPerLot * leg.lots;
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
