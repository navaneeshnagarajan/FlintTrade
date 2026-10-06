/** FlintTrade option-lab contracts, instrument metadata and illustrative Pine programs. */
import { lotSizeFromMaster } from '@/lib/instrumentLots';
export type OptionType = 'CE' | 'PE';
export type Direction = 'BUY' | 'SELL';
export type PremiumSource = 'sample';
export interface Leg { id: string; action: Direction; optionType: OptionType; strike: number; lots: number; premium: number | null; premiumSource?: PremiumSource }
export interface PayoffPoint { price: number; pnl: number }
export interface EquityPoint { bar: number; equity: number }
export interface PerfMetrics { totalReturn: number; totalSignals: number; buySignals: number; sellSignals: number; sharpeApprox: number }
export interface Underlying { symbol: string; exchange: string; lotSize: number | null; strikeGap: number }
export const UNDERLYINGS: Underlying[] = [
  ['NIFTY', 'NSE_INDEX', 50], ['BANKNIFTY', 'NSE_INDEX', 100], ['FINNIFTY', 'NSE_INDEX', 50],
  ['MIDCPNIFTY', 'NSE_INDEX', 25], ['SENSEX', 'BSE_INDEX', 100],
].map(([symbol, exchange, gap]) => ({ symbol: String(symbol), exchange: String(exchange), strikeGap: Number(gap), get lotSize() { return lotSizeFromMaster(String(symbol)); } }));
export { LOADABLE_STRATEGY_TEMPLATES, STRATEGY_TEMPLATES, builderLegsFor, getStrategyTemplate } from '@/lib/strategyTemplates';
export type { StrategyTemplate, StrategyTemplateLeg } from '@/lib/strategyTemplates';
export const EXCHANGES = ['NSE', 'BSE', 'NFO', 'BFO', 'MCX', 'CDS', 'BCD', 'NSE_INDEX', 'BSE_INDEX', 'MCX_INDEX', 'GLOBAL_INDEX'] as const;
export const INTERVALS = ['1m', '3m', '5m', '10m', '15m', '30m', '1h', '2h', '4h', '1d', '1w'] as const;
const crossover = (name: string, average: 'ema' | 'sma', fast: number, slow: number) => `//@version=5
strategy("${name}", overlay=true)
shortAverage = ta.${average}(close, ${fast})
longAverage = ta.${average}(close, ${slow})
plot(shortAverage)
plot(longAverage)
if ta.crossover(shortAverage, longAverage)
    strategy.entry("Long", strategy.long)
if ta.crossunder(shortAverage, longAverage)
    strategy.close("Long")`;
export const PINE_TEMPLATES: Record<string, { label: string; description: string; code: string }> = {
  ema_crossover: { label: 'EMA Crossover', description: 'Illustrative exponential-average cross', code: crossover('Flint EMA study', 'ema', 9, 21) },
  sma_crossover: { label: 'SMA Crossover', description: 'Illustrative moving-average cross', code: crossover('Flint SMA study', 'sma', 20, 50) },
  rsi_mean_reversion: { label: 'RSI Mean Reversion', description: 'Illustrative oversold entry and recovery exit', code: `//@version=5
strategy("Flint RSI study")
momentum = ta.rsi(close, 14)
plot(momentum)
if momentum < 30
    strategy.entry("Long", strategy.long)
if momentum > 50
    strategy.close("Long")` },
  ema_ribbon: { label: 'EMA Ribbon', description: 'Fast and slow average study', code: crossover('Flint ribbon study', 'ema', 8, 34) },
  macd_signal: { label: 'MACD Signal', description: 'Moving-average convergence study', code: `//@version=5
strategy("Flint MACD study")
[macdLine, signalLine, histogram] = ta.macd(close, 12, 26, 9)
plot(histogram)
if ta.crossover(macdLine, signalLine)
    strategy.entry("Long", strategy.long)
if ta.crossunder(macdLine, signalLine)
    strategy.close("Long")` },
};
