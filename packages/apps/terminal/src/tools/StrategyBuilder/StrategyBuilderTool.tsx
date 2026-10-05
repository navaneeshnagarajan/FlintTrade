/** Local option modelling workspace. This tool does not submit orders. */
import { useEffect, useState } from 'react';
import { Button } from '@/components/ui/button';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { sampleChainOptionLtp } from '@/lib/sampleOptionChain';
import { builderLegsFor, getStrategyTemplate } from '@/lib/strategyTemplates';
import { UNDERLYINGS, type Leg } from './types';
import { calculatePositionNetPremium, formatINR, genId } from './utils';
import { LOAD_TEMPLATE_EVENT, readAndClearPendingTemplate, type BuilderTemplate } from './templateBridge';
import { hasPendingPineDraft } from './pineBridge';
import { LegsTab } from './LegsTab';
import { PayoffTab } from './PayoffTab';
import { MarginTab } from './MarginTab';
import { PineTab } from './PineTab';

export default function StrategyBuilderTool({ onClose }: { onClose?: () => void }) {
  const [tab, setTab] = useState(() => hasPendingPineDraft() ? 'pine' : 'legs');
  const [underlying, setUnderlying] = useState(UNDERLYINGS[0]);
  const [atm, setAtm] = useState(22500);
  const [gap, setGap] = useState(50);
  const materialise = (template: BuilderTemplate, price: number, step: number): Leg[] => template.legs.map(shape => {
    const strike = price + shape.strikeOffset * step;
    return { id: genId(), action: shape.action, optionType: shape.optionType, lots: shape.lots,
      strike, premium: sampleChainOptionLtp(price, strike, step, shape.optionType), premiumSource: 'sample' };
  });
  const [legs, setLegs] = useState<Leg[]>(() => {
    const pending = readAndClearPendingTemplate();
    return pending ? materialise(pending, 22500, 50) : [];
  });
  useEffect(() => {
    const load = (event: Event) => {
      const pending = readAndClearPendingTemplate() ?? (event as CustomEvent<BuilderTemplate>).detail;
      if (pending?.legs?.length) { setLegs(materialise(pending, atm, gap)); setTab('legs'); }
    };
    window.addEventListener(LOAD_TEMPLATE_EVENT, load);
    return () => window.removeEventListener(LOAD_TEMPLATE_EVENT, load);
  }, [atm, gap]);
  const net = calculatePositionNetPremium(legs, underlying.lotSize);
  const premiumText = net === null ? 'Premium unavailable' : `${net >= 0 ? 'Debit' : 'Credit'} ${formatINR(Math.abs(net))}`;
  return <section className="flex h-full min-h-0 flex-col text-text-primary">
    <header className="flex items-center justify-between border-b border-border-default p-3">
      <h2 className="font-semibold">Strategy Builder</h2><span>{premiumText}</span>
      {onClose && <Button variant="ghost" onClick={onClose}>Close</Button>}
    </header>
    <Tabs value={tab} onValueChange={setTab} className="flex min-h-0 flex-1 flex-col">
      <TabsList className="justify-start">{[['legs', 'Strategy Legs'], ['payoff', 'Payoff'], ['margin', 'Margin'], ['pine', 'Pine Script']].map(([id, label]) => <TabsTrigger key={id} value={id}>{label}</TabsTrigger>)}</TabsList>
      <TabsContent value="legs" className="min-h-0 flex-1 overflow-auto"><LegsTab legs={legs} atm={atm} onAtmChange={setAtm} underlying={underlying} strikeGap={gap} onStrikeGapChange={setGap}
        onUnderlyingChange={symbol => { const selected = UNDERLYINGS.find(item => item.symbol === symbol); if (selected) { setUnderlying(selected); setGap(selected.strikeGap); } }}
        onAdd={() => setLegs(current => [...current, { id: genId(), action: 'BUY', optionType: 'CE', strike: atm, lots: 1, premium: null }])}
        onRemove={id => setLegs(current => current.filter(leg => leg.id !== id))}
        onChange={(id, field, value) => setLegs(current => current.map(leg => leg.id === id ? { ...leg, [field]: value, ...(field === 'premium' ? { premiumSource: undefined } : {}) } : leg))}
        onTemplate={id => { const template = getStrategyTemplate(id); const shapes = template && builderLegsFor(template); if (template && shapes) setLegs(materialise({ id, name: template.name, legs: shapes }, atm, gap)); }} />
      </TabsContent>
      <TabsContent value="payoff" className="min-h-0 flex-1 overflow-auto"><PayoffTab legs={legs} atm={atm} underlying={underlying} /></TabsContent>
      <TabsContent value="margin" className="min-h-0 flex-1 overflow-auto"><MarginTab legs={legs} underlying={underlying} /></TabsContent>
      <TabsContent value="pine" className="min-h-0 flex-1 overflow-auto"><PineTab /></TabsContent>
    </Tabs>
  </section>;
}
