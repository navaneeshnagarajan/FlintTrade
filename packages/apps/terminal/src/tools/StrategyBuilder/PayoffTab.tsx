/** Analytic payoff summary and sampled expiry valuation, on a position rupee basis. */
import { FlintBaselineSparkline } from '@flinttrade/design-system';
import type { Leg, Underlying } from './types';
import { calculatePositionNetPremium, computePayoff, computePayoffSummary, formatINR, formatPositionSublabel,
  hasExplicitZeroPremium, hasUnsetPremium, SAMPLE_PREMIUM_HELPER, UNSET_PREMIUM_HELPER, ZERO_PREMIUM_WARNING } from './utils';
export function PayoffTab({ legs, atm, underlying }: { legs: Leg[]; atm: number; underlying: Underlying }) {
  const summary = computePayoffSummary(legs);
  const multiplier = underlying.lotSize;
  const net = calculatePositionNetPremium(legs, multiplier);
  const scaled = (value: number | undefined) => value === undefined || multiplier === null ? null : value * multiplier;
  const cards: [string, number | null | string][] = [
    ['Max Profit', scaled(summary?.maxProfit)], ['Max Loss', scaled(summary?.maxLoss)],
    ['Net Premium', net], ['BEP(s)', summary ? summary.breakevens.join(', ') || 'None' : null],
  ];
  const curve = summary ? computePayoff(legs, atm) : [];
  return <div className="space-y-4 p-3">
    <div className="grid grid-cols-2 gap-3 md:grid-cols-4">{cards.map(([label, value]) => <article className="rounded border border-border-default p-3" key={label}>
      <div className="text-xs text-text-secondary">{label}</div>
      <div className="font-mono text-lg">{value === null ? '—' : typeof value === 'string' ? value : formatINR(value)}</div>
      <small className="text-text-muted">{formatPositionSublabel(legs, multiplier, typeof value === 'number' ? value : undefined) ?? 'position'}</small>
    </article>)}</div>
    {hasUnsetPremium(legs) ? <p>{UNSET_PREMIUM_HELPER}</p> : hasExplicitZeroPremium(legs) ? <p>{ZERO_PREMIUM_WARNING}</p> : null}
    {legs.some(leg => leg.premiumSource === 'sample') && <p>{SAMPLE_PREMIUM_HELPER}</p>}
    {multiplier === null && <p>Lot size unavailable. Load the instrument master to model position rupees.</p>}
    {curve.length > 1 && <FlintBaselineSparkline points={curve.map(point => point.pnl)} baseline={0} ariaLabel="Expiry payoff curve" className="h-40 w-full" />}
    {curve.length > 0 && <table className="w-full text-right text-xs"><caption>Sampled expiry payoff per unit, including lot counts</caption><thead><tr><th>Underlying price</th><th>P&amp;L</th></tr></thead><tbody>{curve.filter((_, index) => index % 10 === 0).map(point => <tr key={point.price}><td>{point.price.toFixed(2)}</td><td>{formatINR(point.pnl)}</td></tr>)}</tbody></table>}
    <p className="text-xs text-text-muted">Expiry valuation excludes fees, taxes and changes in implied volatility.</p>
  </div>;
}
