// Types and constants for StrategyBuilder — extracted from StrategyBuilderTool.tsx

export type OptionType = "CE" | "PE";
export type Direction = "BUY" | "SELL";

export interface Leg {
  id: string;
  action: Direction;
  optionType: OptionType;
  strike: number;
  lots: number;
  premium: number;
}

export interface PayoffPoint {
  price: number;
  pnl: number;
}

export interface EquityPoint {
  bar: number;
  equity: number;
}

export interface PerfMetrics {
  totalReturn: number;
  totalSignals: number;
  buySignals: number;
  sellSignals: number;
  sharpeApprox: number;
}

// Default underlyings for Indian F&O
export const UNDERLYINGS = [
  { symbol: "NIFTY",      exchange: "NSE_INDEX", lotSize: 25, strikeGap: 50  },
  { symbol: "BANKNIFTY",  exchange: "NSE_INDEX", lotSize: 15, strikeGap: 100 },
  { symbol: "FINNIFTY",   exchange: "NSE_INDEX", lotSize: 40, strikeGap: 50  },
  { symbol: "MIDCPNIFTY", exchange: "NSE_INDEX", lotSize: 75, strikeGap: 25  },
  { symbol: "SENSEX",     exchange: "BSE_INDEX", lotSize: 10, strikeGap: 100 },
];

export type Underlying = {
  symbol: string;
  exchange: string;
  lotSize: number;
  strikeGap: number;
};

// STRATEGY_TEMPLATES absorbed from openalgo-chart/src/services/strategyTemplates.js
export const STRATEGY_TEMPLATES: Record<
  string,
  { name: string; description: string; legs: { action: Direction; optionType: OptionType; strikeOffset: number; lots: number }[] }
> = {
  straddle: {
    name: "Straddle",
    description: "Buy ATM CE + Buy ATM PE (same strike)",
    legs: [
      { action: "BUY", optionType: "CE", strikeOffset: 0, lots: 1 },
      { action: "BUY", optionType: "PE", strikeOffset: 0, lots: 1 },
    ],
  },
  strangle: {
    name: "Strangle",
    description: "Buy OTM CE + Buy OTM PE (different strikes)",
    legs: [
      { action: "BUY", optionType: "CE", strikeOffset:  1, lots: 1 },
      { action: "BUY", optionType: "PE", strikeOffset: -1, lots: 1 },
    ],
  },
  "short-straddle": {
    name: "Short Straddle",
    description: "Sell ATM CE + Sell ATM PE (theta decay)",
    legs: [
      { action: "SELL", optionType: "CE", strikeOffset: 0, lots: 1 },
      { action: "SELL", optionType: "PE", strikeOffset: 0, lots: 1 },
    ],
  },
  "iron-condor": {
    name: "Iron Condor",
    description: "Sell OTM strangle, buy protection",
    legs: [
      { action: "BUY",  optionType: "PE", strikeOffset: -2, lots: 1 },
      { action: "SELL", optionType: "PE", strikeOffset: -1, lots: 1 },
      { action: "SELL", optionType: "CE", strikeOffset:  1, lots: 1 },
      { action: "BUY",  optionType: "CE", strikeOffset:  2, lots: 1 },
    ],
  },
  butterfly: {
    name: "Butterfly",
    description: "Buy ITM, Sell 2 ATM, Buy OTM CE",
    legs: [
      { action: "BUY",  optionType: "CE", strikeOffset: -1, lots: 1 },
      { action: "SELL", optionType: "CE", strikeOffset:  0, lots: 2 },
      { action: "BUY",  optionType: "CE", strikeOffset:  1, lots: 1 },
    ],
  },
  "bull-call-spread": {
    name: "Bull Call Spread",
    description: "Buy lower strike CE, Sell higher strike CE",
    legs: [
      { action: "BUY",  optionType: "CE", strikeOffset: 0, lots: 1 },
      { action: "SELL", optionType: "CE", strikeOffset: 1, lots: 1 },
    ],
  },
  "bear-put-spread": {
    name: "Bear Put Spread",
    description: "Buy higher strike PE, Sell lower strike PE",
    legs: [
      { action: "BUY",  optionType: "PE", strikeOffset:  0, lots: 1 },
      { action: "SELL", optionType: "PE", strikeOffset: -1, lots: 1 },
    ],
  },
};

// Exchange codes aligned with FlintTrade multi-exchange support.
// Mirrors lib/tradingConstants.EXCHANGES — including the new NCO,
// MCX_INDEX, and GLOBAL_INDEX segments added in the OpenAlgo v2.0.1.1 sync.
export const EXCHANGES = [
  "NSE", "BSE", "NFO", "BFO", "CDS", "BCD", "MCX", "NCDEX", "NCO",
  "NSE_INDEX", "BSE_INDEX", "MCX_INDEX", "GLOBAL_INDEX",
] as const;

// Interval labels — OpenAlgo supported intervals
export const INTERVALS = ["1m", "3m", "5m", "10m", "15m", "30m", "1h", "2h", "4h", "1d", "1w"] as const;

// Pine Script template library
export const PINE_TEMPLATES: Record<string, { label: string; description: string; code: string }> = {
  ema_crossover: {
    label: "EMA Crossover",
    description: "Fast EMA(20) crosses above/below slow EMA(50)",
    code: `//@version=5
strategy("EMA Crossover", overlay=true)
fast = ta.ema(close, 20)
slow = ta.ema(close, 50)
if ta.crossover(fast, slow)
    strategy.entry("Long", strategy.long)
if ta.crossunder(fast, slow)
    strategy.close("Long")
plot(fast, title="EMA 20", color=color.blue)
plot(slow, title="EMA 50", color=color.red)`,
  },
  sma_crossover: {
    label: "SMA Crossover",
    description: "Fast SMA(20) crosses above/below slow SMA(50)",
    code: `//@version=5
strategy("SMA Crossover", overlay=true)
fast = ta.sma(close, 20)
slow = ta.sma(close, 50)
if ta.crossover(fast, slow)
    strategy.entry("Long", strategy.long)
if ta.crossunder(fast, slow)
    strategy.close("Long")
plot(fast, title="SMA 20", color=color.green)
plot(slow, title="SMA 50", color=color.orange)`,
  },
  rsi_mean_reversion: {
    label: "RSI Mean Reversion",
    description: "Buy when RSI dips below 30, exit when above 70",
    code: `//@version=5
strategy("RSI Mean Reversion", overlay=false)
myRsi = ta.rsi(close, 14)
if myRsi < 30
    strategy.entry("Long", strategy.long)
if myRsi > 70
    strategy.close("Long")
plot(myRsi, title="RSI", color=color.purple)`,
  },
  ema_ribbon: {
    label: "EMA Ribbon",
    description: "Three EMAs — 9, 21, 55. Plot only, no signals.",
    code: `//@version=5
strategy("EMA Ribbon", overlay=true)
e9  = ta.ema(close, 9)
e21 = ta.ema(close, 21)
e55 = ta.ema(close, 55)
plot(e9,  title="EMA 9",  color=color.lime)
plot(e21, title="EMA 21", color=color.blue)
plot(e55, title="EMA 55", color=color.orange)`,
  },
  macd_signal: {
    label: "MACD Signal",
    description: "Entry on MACD crossover the signal line",
    code: `//@version=5
strategy("MACD Signal", overlay=false)
myMacd = ta.macd(close, 12, 26, 9)
if ta.crossover(myMacd, myMacd_signal)
    strategy.entry("Long", strategy.long)
if ta.crossunder(myMacd, myMacd_signal)
    strategy.close("Long")
plot(myMacd,        title="MACD",   color=color.blue)
plot(myMacd_signal, title="Signal", color=color.orange)`,
  },
};
