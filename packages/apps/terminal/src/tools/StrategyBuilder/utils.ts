/** Vanilla-option valuation and local signal simulation for the FlintTrade lab. */
import type { EquityPoint, Leg, PayoffPoint, PerfMetrics, Underlying } from './types';

export const UNSET_PREMIUM_HELPER = 'Enter premium to model payoff';
export const SAMPLE_PREMIUM_HELPER = 'Example premium — edit to model';
export const ZERO_PREMIUM_WARNING = 'Premium is ₹0 — payoff treats cost as free';
export const POSITION_BASIS_TAG = 'position';

export const isPricedPremium = (value: unknown): value is number =>
  typeof value === 'number' && Number.isFinite(value) && value >= 0;
export const hasUnsetPremium = (legs: readonly Leg[]) => legs.some(leg => !isPricedPremium(leg.premium));
export const hasExplicitZeroPremium = (legs: readonly Leg[]) => legs.some(leg => leg.premium === 0);
export function parsePremiumInput(value: string): number | null {
  const parsed = value.trim() ? Number(value) : NaN;
  return isPricedPremium(parsed) ? parsed : null;
}
export function calculateNetPremium(legs: readonly Leg[]): number | null {
  if (hasUnsetPremium(legs)) return null;
  return legs.reduce((sum, leg) => sum + (leg.action === 'BUY' ? 1 : -1) * leg.premium! * leg.lots, 0);
}
export function calculatePositionNetPremium(legs: readonly Leg[], lotSize: number | null): number | null {
  const premium = calculateNetPremium(legs);
  return premium !== null && lotSize !== null && lotSize > 0 ? premium * lotSize : null;
}
export function uniformLotCount(legs: readonly Leg[]): number | null {
  const count = legs[0]?.lots;
  return count && legs.every(leg => leg.lots === count) ? count : null;
}
export function formatINR(value: number): string {
  if (!Number.isFinite(value)) return value === Infinity ? 'Unlimited' : value === -Infinity ? 'Unlimited' : '—';
  return new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 2 }).format(value);
}
export function formatPositionSublabel(legs: readonly Leg[], lotSize: number | null, positionRupees?: number | null): string | null {
  const lots = uniformLotCount(legs);
  const total = positionRupees === undefined ? calculatePositionNetPremium(legs, lotSize) : positionRupees;
  if (lots === null || lotSize === null || total === null || !Number.isFinite(total)) return null;
  return `${formatINR(Math.abs(total) / lots)} per lot · ${lots} ${lots === 1 ? 'lot' : 'lots'} · lot size ${lotSize}`;
}
export function validateLegs(legs: Leg[]): { valid: boolean; error: string | null } {
  const invalid = legs.find(leg => !Number.isFinite(leg.strike) || leg.strike <= 0 || !Number.isInteger(leg.lots) || leg.lots <= 0 ||
    !['BUY', 'SELL'].includes(leg.action) || !['CE', 'PE'].includes(leg.optionType) || (leg.premium !== null && !isPricedPremium(leg.premium)));
  return { valid: legs.length > 0 && !invalid, error: invalid ? 'Enter a positive strike and whole number of lots' : legs.length ? null : 'Add a strategy leg' };
}
export const genId = () => crypto.randomUUID();
export function pnlAtExpiry(legs: Leg[], price: number): number {
  return legs.reduce((sum, leg) => {
    const intrinsic = Math.max(0, leg.optionType === 'CE' ? price - leg.strike : leg.strike - price);
    return sum + (leg.action === 'BUY' ? 1 : -1) * leg.lots * (intrinsic - (leg.premium ?? 0));
  }, 0);
}
export interface PayoffSummary { maxProfit: number; maxLoss: number; breakevens: number[] }
/** A vanilla portfolio is affine between strikes. Kinks determine every bounded extremum. */
export function computePayoffSummary(legs: Leg[]): PayoffSummary | null {
  if (!validateLegs(legs).valid || hasUnsetPremium(legs)) return null;
  const boundaries = [...new Set([0, ...legs.map(leg => leg.strike)])].sort((a, b) => a - b);
  const values = boundaries.map(price => pnlAtExpiry(legs, price));
  const tailSlope = legs.filter(leg => leg.optionType === 'CE').reduce((sum, leg) => sum + (leg.action === 'BUY' ? 1 : -1) * leg.lots, 0);
  const roots = new Set<number>();
  for (let index = 1; index < boundaries.length; index++) {
    const left = boundaries[index - 1], right = boundaries[index];
    const lower = values[index - 1], upper = values[index];
    if (lower * upper < 0) roots.add(left - lower * (right - left) / (upper - lower));
    // A zero plateau has infinitely many roots; report its strike boundary.
    if (upper === 0 && right > 0) roots.add(right);
    if (lower === 0 && left > 0) roots.add(left);
  }
  const last = boundaries.at(-1)!, lastValue = values.at(-1)!;
  if (tailSlope && -lastValue / tailSlope > 0) roots.add(last - lastValue / tailSlope);
  return {
    maxProfit: tailSlope > 0 ? Infinity : Math.max(...values),
    maxLoss: tailSlope < 0 ? -Infinity : Math.min(...values),
    breakevens: [...roots].sort((a, b) => a - b),
  };
}
export function computePayoff(legs: Leg[], spotPrice: number): PayoffPoint[] {
  return Array.from({ length: 101 }, (_, index) => {
    const price = spotPrice * (85 + index * 0.3) / 100;
    return { price, pnl: pnlAtExpiry(legs, price) };
  });
}
/** Local planning estimate only. Broker margin is a separate authorised read. */
export function estimateMargin(legs: Leg[], underlying: Underlying): number | null {
  const lot = underlying.lotSize;
  const summary = computePayoffSummary(legs);
  if (!summary || lot === null || lot <= 0) return null;
  if (Number.isFinite(summary.maxLoss)) return Math.max(0, -summary.maxLoss * lot);
  const debit = Math.max(0, calculateNetPremium(legs) ?? 0) * lot;
  const shortNotional = legs.filter(leg => leg.action === 'SELL').reduce((sum, leg) => sum + leg.strike * leg.lots * lot, 0);
  return debit + shortNotional * 0.2;
}
export function computeEquityCurve(bars: { close: number }[], signals: { bar: number; type: 'BUY' | 'SELL' }[]): EquityPoint[] {
  const events = new Map(signals.map(signal => [signal.bar, signal.type]));
  let cash = 10_000, shares = 0, lastClose = 0;
  return bars.map((bar, index) => {
    if (Number.isFinite(bar.close) && bar.close > 0) {
      lastClose = bar.close;
      if (events.get(index) === 'BUY' && shares === 0) { shares = cash / bar.close; cash = 0; }
      if (events.get(index) === 'SELL' && shares > 0) { cash = shares * bar.close; shares = 0; }
    }
    // An unusable bar cannot fill a signal or replace the last valid valuation.
    return { bar: index, equity: cash + shares * lastClose };
  });
}
export function computeMetrics(bars: { close: number }[], signals: { bar: number; type: 'BUY' | 'SELL' }[]): PerfMetrics {
  const curve = computeEquityCurve(bars, signals);
  const returns = curve.slice(1).map((point, index) => curve[index].equity > 0 ? point.equity / curve[index].equity - 1 : 0);
  const mean = returns.reduce((a, b) => a + b, 0) / (returns.length || 1);
  const deviation = Math.sqrt(returns.reduce((sum, value) => sum + (value - mean) ** 2, 0) / (returns.length || 1));
  return { totalReturn: ((curve.at(-1)?.equity ?? 10_000) / 10_000 - 1) * 100,
    totalSignals: signals.length, buySignals: signals.filter(signal => signal.type === 'BUY').length,
    sellSignals: signals.filter(signal => signal.type === 'SELL').length, sharpeApprox: deviation ? mean / deviation * Math.sqrt(252) : 0 };
}
