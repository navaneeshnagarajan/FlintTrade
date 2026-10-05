/** Exact-contract option basket editor using FlintTrade templates and gated orders. */
import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from 'react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { buildCompactOptionSymbol } from '@/lib/optionSymbols';
import { builderLegsFor, CUSTOM_TEMPLATE, getStrategyTemplate } from '@/lib/strategyTemplates';
import { basketOrder, OrderApiError } from '@/services/api';
import { assertNativeWriteTargetReadyOrThrow } from '@/services/brokerTargets';
import { useModeStore } from '@/stores/modeStore';
import { useBrokerStore } from '@/stores/brokerStore';
import { useMarketDataScope, resolveMarketDataScope } from '@/hooks/useDataScope';
import { computePayoffSummary, formatINR } from '@/tools/StrategyBuilder/utils';
import type { StrikeRow } from './types';
import type { BasketOrderResult } from '@/types/api';
export interface OptionLeg { id: string; side: 'BUY' | 'SELL'; optionType: 'CE' | 'PE'; strike: number; lots: number; premium: number | null }
export interface LegBuilderHandle { addLegFromStrike: (strike: number, optionType: 'CE' | 'PE') => void }
export interface LegBuilderProps { strikes: StrikeRow[]; atmStrike: number | null; lotSize: number; symLabel: string; exchange: string; expiry: string | null; onClose: () => void; spotPrice?: number }
const choices = ['short-straddle', 'short-strangle', 'bull-call-spread', 'bear-put-spread', 'bull-put-spread', 'bear-call-spread', 'iron-condor', 'butterfly'];
function executionMessage(result: BasketOrderResult): { text: string; urgent: boolean } {
  const placed = result.placed_count, failed = result.failed_count;
  if (!Number.isInteger(placed) || !Number.isInteger(failed) || placed < 0 || failed < 0) return { text: 'Basket outcome unavailable — check Orders and Positions.', urgent: true };
  if (!failed) return { text: `${placed} ${placed === 1 ? 'leg' : 'legs'} placed`, urgent: false };
  const confirmed = result.legs?.filter(leg => leg.success && leg.rolled_back && leg.rollback_order_id).length ?? 0;
  const detail = result.message ? ` — ${result.message}` : '';
  const unconfirmed = placed > confirmed;
  return { text: `${placed} ${placed === 1 ? 'leg' : 'legs'} placed${placed > 0 && !unconfirmed ? ' then rolled back' : ''}, ${failed} failed${detail}${unconfirmed ? '. Rollback unconfirmed — check Positions.' : ''}`, urgent: unconfirmed };
}
const LegBuilder = forwardRef<LegBuilderHandle, LegBuilderProps>((props, ref) => {
  const mode = useModeStore(state => state.mode);
  const dataScope = useMarketDataScope();
  const identity = `${dataScope}:${props.symLabel}:${props.exchange}:${props.expiry}`;
  const [state, setState] = useState<{ identity: string; legs: OptionLeg[] }>({ identity, legs: [] });
  const legs = state.identity === identity ? state.legs : [];
  const [templateId, setTemplateId] = useState('custom');
  const [message, setMessage] = useState<{ text: string; urgent: boolean } | null>(null);
  const [busy, setBusy] = useState(false);
  const current = useRef(identity); current.current = identity;
  const mounted = useRef(true);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  useEffect(() => { setMessage(null); setBusy(false); setTemplateId('custom'); }, [identity]);
  useEffect(() => {
    if (!message || message.urgent) return;
    const timer = setTimeout(() => setMessage(null), 4000);
    return () => clearTimeout(timer);
  }, [message]);
  const price = (strike: number, type: 'CE' | 'PE') => {
    const row = props.strikes.find(candidate => candidate.strike === strike);
    const quote = type === 'CE' ? row?.call : row?.put;
    const value = quote?.ltp ?? quote?.last_price;
    return typeof value === 'number' && Number.isFinite(value) && value >= 0 ? value : null;
  };
  const makeLeg = (strike: number, type: 'CE' | 'PE', side: 'BUY' | 'SELL' = 'BUY', lots = 1): OptionLeg => ({ id: crypto.randomUUID(), strike, optionType: type, side, lots, premium: price(strike, type) });
  const update = (next: OptionLeg[]) => setState({ identity, legs: next });
  const add = (strike: number, type: 'CE' | 'PE', toggle = false) => {
    setTemplateId('custom');
    setState(previous => {
      const rows = previous.identity === identity ? previous.legs : [];
      const duplicate = rows.find(leg => leg.strike === strike && leg.optionType === type);
      return { identity, legs: toggle && duplicate ? rows.filter(leg => leg.id !== duplicate.id) : rows.length < 4 ? [...rows, makeLeg(strike, type)] : rows };
    });
  };
  useImperativeHandle(ref, () => ({ addLegFromStrike: (strike, type) => add(strike, type, true) }));
  const select = (id: string) => {
    setTemplateId(id);
    if (id === 'custom') { update([]); return; }
    const template = getStrategyTemplate(id), shapes = template && builderLegsFor(template);
    if (!shapes || props.atmStrike === null) { update([]); return; }
    const ordered = [...new Set(props.strikes.map(row => row.strike))].sort((a, b) => a - b);
    const gap = ordered.length > 1 ? ordered[1] - ordered[0] : 50;
    update(shapes.map(shape => makeLeg(props.atmStrike! + shape.strikeOffset * gap, shape.optionType, shape.action, shape.lots)));
  };
  const modelLegs = legs.map(leg => ({ ...leg, action: leg.side }));
  const summary = computePayoffSummary(modelLegs);
  const premium = legs.every(leg => leg.premium !== null) ? legs.reduce((sum, leg) => sum + (leg.side === 'BUY' ? 1 : -1) * leg.premium! * leg.lots * props.lotSize, 0) : null;
  const lotVerified = Number.isSafeInteger(props.lotSize) && props.lotSize > 0;
  const quantitiesValid = legs.every(leg => Number.isSafeInteger(leg.lots) && leg.lots > 0 && Number.isSafeInteger(leg.lots * props.lotSize) && Number.isFinite(leg.strike) && leg.strike > 0);
  const place = async () => {
    const pinnedIdentity = identity;
    const activeMode = useModeStore.getState().mode;
    const brokerState = useBrokerStore.getState();
    const actualScope = resolveMarketDataScope({ mode: activeMode, accounts: brokerState.accounts, activeAccountId: brokerState.activeAccountId });
    if (busy || current.current !== pinnedIdentity || actualScope !== dataScope || activeMode !== mode || activeMode === 'explore' || !lotVerified || !quantitiesValid || !legs.length) return;
    if (!props.expiry) { setMessage({ text: 'Select an expiry first', urgent: false }); return; }
    try {
      assertNativeWriteTargetReadyOrThrow(activeMode);
      setBusy(true); setMessage(null);
      const orders = legs.map(leg => {
        const symbol = buildCompactOptionSymbol(props.symLabel, props.expiry!, leg.strike, leg.optionType);
        if (!symbol) throw new Error('Option contract identity is incomplete');
        return { symbol, exchange: props.exchange, action: leg.side, quantity: leg.lots * props.lotSize, orderType: 'MARKET' as const, product: 'MIS' as const };
      });
      const result = await basketOrder({ strategy: 'FlintLegBuilder', orders });
      if (mounted.current && current.current === pinnedIdentity) setMessage(executionMessage(result));
    } catch (error) {
      if (mounted.current && current.current === pinnedIdentity) {
        const outcome = error instanceof OrderApiError && error.body && typeof error.body === 'object' && 'placed_count' in error.body ? executionMessage(error.body as BasketOrderResult) : { text: error instanceof Error ? error.message : 'Basket submission failed', urgent: false };
        setMessage(outcome);
      }
    } finally { if (mounted.current && current.current === pinnedIdentity) setBusy(false); }
  };
  return <section role="region" aria-label="Strategy leg builder" className="space-y-3 border-l border-border-default p-3 text-xs">
    <header className="flex justify-between"><h3>Strategy Builder</h3><Button variant="ghost" size="sm" aria-label="Close strategy builder" onClick={props.onClose}>Close</Button></header>
    <nav className="flex flex-wrap gap-1">{[...choices.map(id => getStrategyTemplate(id)!).filter(Boolean), CUSTOM_TEMPLATE].map(template => <Button key={template.id} size="sm" variant="outline" aria-label={template.name} aria-pressed={templateId === template.id} onClick={() => select(template.id)}>{template.shortName}</Button>)}</nav>
    {!legs.length && <p>Choose a template above or add a leg.</p>}
    {legs.map(leg => <div key={leg.id} className="flex flex-wrap items-center gap-1 rounded border border-border-default p-2">
      {(['BUY', 'SELL'] as const).map(side => <Button key={side} size="sm" variant={leg.side === side ? 'default' : 'outline'} aria-pressed={leg.side === side} onClick={() => update(legs.map(row => row.id === leg.id ? { ...row, side } : row))}>{side === 'BUY' ? 'B' : 'S'}</Button>)}
      {(['CE', 'PE'] as const).map(type => <Button key={type} size="sm" variant={leg.optionType === type ? 'default' : 'outline'} onClick={() => update(legs.map(row => row.id === leg.id ? { ...row, optionType: type, premium: price(row.strike, type) } : row))}>{type}</Button>)}
      <select aria-label="Strike price" value={leg.strike} onChange={event => { const strike = Number(event.target.value); update(legs.map(row => row.id === leg.id ? { ...row, strike, premium: price(strike, row.optionType) } : row)); }}>{[...new Set([leg.strike, ...props.strikes.map(row => row.strike)])].sort((a,b) => a-b).map(strike => <option key={strike} value={strike}>{strike}</option>)}</select>
      <Input className="w-16" aria-label="Number of lots" type="number" min={1} step={1} value={leg.lots} onChange={event => update(legs.map(row => row.id === leg.id ? { ...row, lots: Number(event.target.value) } : row))} />
      <span>{leg.premium === null ? 'Premium unavailable' : formatINR(leg.premium)}</span><Button variant="ghost" size="sm" aria-label="Remove leg" onClick={() => update(legs.filter(row => row.id !== leg.id))}>Remove</Button>
    </div>)}
    {legs.length < 4 && <Button size="sm" onClick={() => add(props.atmStrike ?? props.strikes[0]?.strike ?? 0, 'CE')}>Add Leg</Button>}
    {legs.length > 0 && <footer className="space-y-2"><p>Net {premium === null ? '—' : `${premium < 0 ? 'Credit' : 'Debit'} ${formatINR(Math.abs(premium))}`}</p>{summary && <p>B/E {summary.breakevens.join(', ') || 'None'} · Max profit {formatINR(summary.maxProfit * props.lotSize)} · Max loss {formatINR(summary.maxLoss * props.lotSize)}</p>}
      {!lotVerified && <p>Lot size unverified</p>}<Button aria-label="Place strategy" disabled={busy || mode === 'explore' || !lotVerified || !quantitiesValid} onClick={() => void place()}>{busy ? 'Submitting…' : 'Place Strategy'}</Button></footer>}
    {message && <p role={message.urgent ? 'alert' : 'status'}>{message.text}</p>}
  </section>;
});
LegBuilder.displayName = 'LegBuilder';
export default LegBuilder;
