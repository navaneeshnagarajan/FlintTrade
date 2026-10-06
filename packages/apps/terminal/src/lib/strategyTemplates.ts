/** Vanilla option recipes expressed in FlintTrade's exact-contract builder schema. */
import type { BuilderTemplateLeg } from '@/tools/StrategyBuilder/templateBridge';
export type StrategyOutlook = 'bullish' | 'bearish' | 'neutral' | 'volatile';
export type StrategyLegAction = 'BUY' | 'SELL';
export type StrategyLegInstrument = 'CE' | 'PE' | 'STOCK';
export type StrategyStrikeLabel = 'ITM' | 'ATM' | 'OTM';
export interface StrategyTemplateLeg {
  action: StrategyLegAction;
  optionType: StrategyLegInstrument;
  strikeOffset?: number;
  lots: number;
  strikeLabel?: StrategyStrikeLabel;
  expiry?: 'near' | 'far';
}
export interface StrategyTemplate {
  id: string;
  name: string;
  shortName: string;
  outlook: StrategyOutlook;
  description: string;
  maxProfit: string;
  maxLoss: string;
  breakeven: string;
  legs: readonly StrategyTemplateLeg[];
}
/** Reject the entire recipe if an options basket cannot represent every leg. */
export function builderLegsFor(template: StrategyTemplate): BuilderTemplateLeg[] | null {
  if (!template.legs.length || template.legs.length > 4) return null;
  const result: BuilderTemplateLeg[] = [];
  for (const leg of template.legs) {
    if ((leg.action !== 'BUY' && leg.action !== 'SELL') ||
        (leg.optionType !== 'CE' && leg.optionType !== 'PE') || leg.expiry !== undefined ||
        !Number.isFinite(leg.strikeOffset) || !Number.isSafeInteger(leg.lots) || leg.lots < 1) return null;
    result.push({ action: leg.action, optionType: leg.optionType, strikeOffset: leg.strikeOffset!, lots: leg.lots });
  }
  return result;
}
export const isLoadable = (template: StrategyTemplate): boolean => builderLegsFor(template) !== null;
const option = (action: StrategyLegAction, optionType: 'CE' | 'PE', strikeOffset: number, lots = 1): StrategyTemplateLeg => ({ action, optionType, strikeOffset, lots });
const stock: StrategyTemplateLeg = { action: 'BUY', optionType: 'STOCK', lots: 1 };
const recipe = (id: string, name: string, shortName: string, outlook: StrategyOutlook, description: string,
  maxProfit: string, maxLoss: string, breakeven: string, legs: StrategyTemplateLeg[]): StrategyTemplate =>
  ({ id, name, shortName, outlook, description, maxProfit, maxLoss, breakeven, legs });
const debit = 'Entry premium paid';
const credit = 'Entry premium received';
const verticalProfit = 'Strike width less entry debit';
const verticalLoss = 'Strike width less entry credit';
export const STRATEGY_TEMPLATES: readonly StrategyTemplate[] = [
  recipe('long-call', 'Long Call', 'LC', 'bullish', 'Buy a call to participate above its strike.', 'Unlimited', debit, 'Call strike plus premium', [option('BUY','CE',0)]),
  recipe('long-put', 'Long Put', 'LP', 'bearish', 'Buy a put to participate below its strike.', 'Put strike less premium (at zero)', debit, 'Put strike less premium', [option('BUY','PE',0)]),
  recipe('long-straddle', 'Long Straddle', 'LSTR', 'volatile', 'Buy both option rights at the same strike.', 'Unlimited', debit, 'Strike plus or minus total premium', [option('BUY','CE',0), option('BUY','PE',0)]),
  recipe('short-straddle', 'Short Straddle', 'SSTR', 'neutral', 'Sell both option rights at the same strike; upside losses have no cap.', credit, 'Unlimited', 'Strike plus or minus total premium', [option('SELL','CE',0), option('SELL','PE',0)]),
  recipe('long-strangle', 'Long Strangle', 'LSTG', 'volatile', 'Buy a lower put and a higher call.', 'Unlimited', debit, 'Put strike less debit; call strike plus debit', [option('BUY','PE',-1), option('BUY','CE',1)]),
  recipe('short-strangle', 'Short Strangle', 'SSTG', 'neutral', 'Sell a lower put and a higher call; upside losses have no cap.', credit, 'Unlimited', 'Put strike less credit; call strike plus credit', [option('SELL','PE',-1), option('SELL','CE',1)]),
  recipe('bull-call-spread', 'Bull Call Spread', 'BCS', 'bullish', 'Buy a lower call and sell a higher call.', verticalProfit, debit, 'Lower call strike plus debit', [option('BUY','CE',0), option('SELL','CE',1)]),
  recipe('bear-call-spread', 'Bear Call Spread', 'BECS', 'bearish', 'Sell a lower call and buy a higher call.', credit, verticalLoss, 'Lower call strike plus credit', [option('SELL','CE',0), option('BUY','CE',1)]),
  recipe('bear-put-spread', 'Bear Put Spread', 'BPS', 'bearish', 'Sell a lower put and buy a higher put.', verticalProfit, debit, 'Higher put strike less debit', [option('SELL','PE',-1), option('BUY','PE',0)]),
  recipe('bull-put-spread', 'Bull Put Spread', 'BUPS', 'bullish', 'Buy a lower put and sell a higher put.', credit, verticalLoss, 'Higher put strike less credit', [option('BUY','PE',-1), option('SELL','PE',0)]),
  recipe('iron-condor', 'Iron Condor', 'IC', 'neutral', 'Sell an inner put and call, protected by outer wings.', credit, 'Larger wing width less entry credit', 'Short put less credit; short call plus credit', [option('BUY','PE',-2), option('SELL','PE',-1), option('SELL','CE',1), option('BUY','CE',2)]),
  recipe('butterfly', 'Butterfly', 'BF', 'neutral', 'Buy equal call wings around two sold centre calls.', 'Wing width less entry debit', debit, 'Lower strike plus debit; upper strike less debit', [option('BUY','CE',-1), option('SELL','CE',0,2), option('BUY','CE',1)]),
  recipe('covered-call', 'Covered Call', 'CC', 'neutral', 'Hold shares and sell a call against them.', 'Call strike less share cost plus credit', 'Share cost less credit (at zero)', 'Share cost less credit', [stock, option('SELL','CE',1)]),
  recipe('protective-put', 'Protective Put', 'PP', 'bullish', 'Hold shares with a bought downside put.', 'Unlimited', 'Share cost plus premium less put strike', 'Share cost plus premium', [stock, option('BUY','PE',-1)]),
  recipe('collar', 'Collar', 'COL', 'neutral', 'Hold shares between a bought put and a sold call.', 'Call strike less share cost less net premium', 'Share cost plus net premium less put strike', 'Share cost plus net premium', [stock, option('BUY','PE',-1), option('SELL','CE',1)]),
  recipe('calendar-spread', 'Calendar Spread', 'CAL', 'neutral', 'Sell a near-expiry call and buy the same strike at a later expiry.', 'Depends on volatility and remaining time value', 'Entry debit for the matched calendar', 'Requires a model at the near expiry', [{ ...option('SELL','CE',0), expiry:'near' }, { ...option('BUY','CE',0), expiry:'far' }]),
];
export const LOADABLE_STRATEGY_TEMPLATES = STRATEGY_TEMPLATES.filter(isLoadable);
export const CUSTOM_TEMPLATE_ID = 'custom';
export const CUSTOM_TEMPLATE: StrategyTemplate = recipe(CUSTOM_TEMPLATE_ID, 'Custom', 'CUST', 'neutral', 'Build an explicit option basket.', 'Calculated from legs', 'Calculated from legs', 'Calculated from legs', []);
export function getStrategyTemplate(id: string): StrategyTemplate | undefined {
  return id === CUSTOM_TEMPLATE_ID ? CUSTOM_TEMPLATE : STRATEGY_TEMPLATES.find(template => template.id === id);
}
