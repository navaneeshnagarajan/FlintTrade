/** Editable option legs using FlintTrade's shared strategy catalogue. */
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { LOADABLE_STRATEGY_TEMPLATES } from '@/lib/strategyTemplates';
import { analyseVerticalSpread } from '@/lib/spreadAnalysis';
import { UNDERLYINGS, type Leg, type Underlying } from './types';
import { SAMPLE_PREMIUM_HELPER, calculatePositionNetPremium, formatINR, parsePremiumInput, validateLegs } from './utils';
interface Props {
  legs: Leg[]; onAdd: () => void; onRemove: (id: string) => void;
  onChange: (id: string, field: keyof Leg, value: unknown) => void;
  onTemplate: (key: string) => void; atm: number; onAtmChange: (value: number) => void;
  underlying: Underlying; onUnderlyingChange: (symbol: string) => void;
  strikeGap: number; onStrikeGapChange: (value: number) => void;
}
export function LegsTab(props: Props) {
  const { legs, underlying } = props;
  const net = calculatePositionNetPremium(legs, underlying.lotSize);
  const validation = validateLegs(legs);
  const spread = underlying.lotSize === null ? null : analyseVerticalSpread(legs, underlying.lotSize);
  return <div className="space-y-4 p-3">
    <div className="flex flex-wrap gap-3">
      <label>Underlying<select aria-label="Underlying" value={underlying.symbol} onChange={event => props.onUnderlyingChange(event.target.value)}>{UNDERLYINGS.map(item => <option key={item.symbol}>{item.symbol}</option>)}</select></label>
      <label>ATM<Input aria-label="ATM" type="number" value={props.atm} onChange={event => props.onAtmChange(Number(event.target.value))} /></label>
      <label>Strike gap<Input aria-label="Strike gap" type="number" min={1} value={props.strikeGap} onChange={event => props.onStrikeGapChange(Number(event.target.value))} /></label>
    </div>
    <nav aria-label="Option strategy templates" className="flex flex-wrap gap-2">{LOADABLE_STRATEGY_TEMPLATES.map(template => <Button key={template.id} variant="outline" size="sm" onClick={() => props.onTemplate(template.id)}>{template.name}</Button>)}</nav>
    {!legs.length && <p>Add a leg or select a strategy template.</p>}
    {legs.map((leg, index) => <fieldset key={leg.id} className="grid grid-cols-2 gap-2 rounded border border-border-default p-3 sm:grid-cols-6"><legend>Leg {index + 1}</legend>
      <label>Action<select aria-label="Action" value={leg.action} onChange={event => props.onChange(leg.id, 'action', event.target.value)}><option>BUY</option><option>SELL</option></select></label>
      <label>Option type<select aria-label="Option type" value={leg.optionType} onChange={event => props.onChange(leg.id, 'optionType', event.target.value)}><option>CE</option><option>PE</option></select></label>
      <label>Strike<Input aria-label="Strike" type="number" min={1} value={leg.strike} onChange={event => props.onChange(leg.id, 'strike', Number(event.target.value))} /></label>
      <label>Lots<Input aria-label="Lots" type="number" min={1} step={1} value={leg.lots} onChange={event => props.onChange(leg.id, 'lots', Number(event.target.value))} /></label>
      <label>Premium<Input aria-label="Premium" type="number" min={0} value={leg.premium ?? ''} onChange={event => props.onChange(leg.id, 'premium', parsePremiumInput(event.target.value))} /></label>
      <Button variant="ghost" aria-label={`Remove leg ${index + 1}`} onClick={() => props.onRemove(leg.id)}>Remove</Button>
    </fieldset>)}
    <Button onClick={props.onAdd}>Add Leg</Button>
    {legs.length > 0 && <p>{net === null ? 'Premium unavailable' : `${net >= 0 ? 'Debit' : 'Credit'} ${formatINR(Math.abs(net))}`}</p>}
    {legs.some(leg => leg.premiumSource === 'sample') && <p>{SAMPLE_PREMIUM_HELPER}</p>}
    {!validation.valid && legs.length > 0 && <p role="alert">{validation.error}</p>}
    {spread?.kind === 'invalid' && <p role="alert">{spread.error}</p>}
    {spread?.kind === 'valid' && <p>Vertical spread max loss: {formatINR(spread.metrics.maxLoss)}</p>}
  </div>;
}
