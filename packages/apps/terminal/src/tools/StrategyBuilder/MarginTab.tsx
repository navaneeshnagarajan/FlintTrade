/** Planning-only option collateral estimate. No execution authority. */
import type { Leg, Underlying } from './types';
import { calculatePositionNetPremium, estimateMargin, formatINR, hasUnsetPremium, UNSET_PREMIUM_HELPER } from './utils';
export function MarginTab({ legs, underlying }: { legs: Leg[]; underlying: Underlying }) {
  const margin = estimateMargin(legs, underlying);
  const premium = calculatePositionNetPremium(legs, underlying.lotSize);
  return <div className="space-y-4 p-4"><h3>Illustrative margin</h3>
    <dl className="grid grid-cols-2 gap-3"><dt>Planning estimate</dt><dd>{margin === null ? '—' : formatINR(margin)}</dd>
      <dt>Net premium</dt><dd>{premium === null ? '—' : formatINR(premium)}</dd>
      <dt>Lot size</dt><dd>{underlying.lotSize ?? 'Unavailable'}</dd></dl>
    {hasUnsetPremium(legs) && <p>{UNSET_PREMIUM_HELPER}</p>}
    <p>Bounded expiry loss is the planning floor. Unbounded short positions use an illustrative 20% of strike notional.</p>
    <p>Confirm actual required margin with your broker. This estimate does not model SPAN, exposure add-ons, intraday changes or portfolio offsets.</p>
  </div>;
}
