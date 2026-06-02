import { type JournalTrade } from "@/services/ftApi";

const SAMPLE_LIMIT = 200;

type SampleTradeInput = Omit<JournalTrade, "timestamp"> & {
  daysAgo: number;
  hour: number;
  minute: number;
};

function timestampFor(daysAgo: number, hour: number, minute: number): string {
  const date = new Date();
  date.setDate(date.getDate() - daysAgo);
  date.setHours(hour, minute, 0, 0);
  return date.toISOString();
}

function makeTrade(input: SampleTradeInput): JournalTrade {
  const { daysAgo, hour, minute, ...trade } = input;
  return {
    ...trade,
    timestamp: timestampFor(daysAgo, hour, minute),
  };
}

function buildSampleJournalTrades(): JournalTrade[] {
  const trades: SampleTradeInput[] = [
    {
      action: "BUY",
      daysAgo: 6,
      entry_price: 23120,
      exchange: "NFO",
      exit_price: 23192,
      fees: 88,
      hour: 9,
      minute: 32,
      pnl: 1800,
      price: 23120,
      quantity: 50,
      strategy: "Opening Range",
      symbol: "NIFTY",
    },
    {
      action: "SELL",
      daysAgo: 6,
      entry_price: 23210,
      exchange: "NFO",
      exit_price: 23174,
      fees: 86,
      hour: 10,
      minute: 14,
      pnl: 900,
      price: 23210,
      quantity: 50,
      strategy: "Opening Range",
      symbol: "NIFTY",
    },
    {
      action: "BUY",
      daysAgo: 5,
      entry_price: 51240,
      exchange: "NFO",
      exit_price: 51155,
      fees: 112,
      hour: 9,
      minute: 48,
      pnl: -1275,
      price: 51240,
      quantity: 15,
      strategy: "VWAP Reclaim",
      symbol: "BANKNIFTY",
    },
    {
      action: "BUY",
      daysAgo: 5,
      entry_price: 23180,
      exchange: "NFO",
      exit_price: 23254,
      fees: 91,
      hour: 13,
      minute: 7,
      pnl: 1850,
      price: 23180,
      quantity: 50,
      strategy: "VWAP Reclaim",
      symbol: "NIFTY",
    },
    {
      action: "SELL",
      daysAgo: 4,
      entry_price: 1038,
      exchange: "NSE",
      exit_price: 1024,
      fees: 64,
      hour: 10,
      minute: 3,
      pnl: 700,
      price: 1038,
      quantity: 50,
      strategy: "Gap Fade",
      symbol: "RELIANCE",
    },
    {
      action: "BUY",
      daysAgo: 4,
      entry_price: 1624,
      exchange: "NSE",
      exit_price: 1613,
      fees: 59,
      hour: 14,
      minute: 21,
      pnl: -550,
      price: 1624,
      quantity: 50,
      strategy: "Gap Fade",
      symbol: "HDFCBANK",
    },
    {
      action: "BUY",
      daysAgo: 3,
      entry_price: 23220,
      exchange: "NFO",
      exit_price: 23186,
      fees: 90,
      hour: 9,
      minute: 35,
      pnl: -850,
      price: 23220,
      quantity: 50,
      strategy: "Momentum Pullback",
      symbol: "NIFTY",
    },
    {
      action: "SELL",
      daysAgo: 3,
      entry_price: 51460,
      exchange: "NFO",
      exit_price: 51325,
      fees: 118,
      hour: 11,
      minute: 2,
      pnl: 2025,
      price: 51460,
      quantity: 15,
      strategy: "Momentum Pullback",
      symbol: "BANKNIFTY",
    },
    {
      action: "BUY",
      daysAgo: 2,
      entry_price: 2368,
      exchange: "NSE",
      exit_price: 2386,
      fees: 74,
      hour: 10,
      minute: 42,
      pnl: 1260,
      price: 2368,
      quantity: 70,
      strategy: "VWAP Reclaim",
      symbol: "INFY",
    },
    {
      action: "SELL",
      daysAgo: 2,
      entry_price: 3914,
      exchange: "NSE",
      exit_price: 3931,
      fees: 69,
      hour: 14,
      minute: 7,
      pnl: -680,
      price: 3914,
      quantity: 40,
      strategy: "VWAP Reclaim",
      symbol: "TCS",
    },
    {
      action: "BUY",
      daysAgo: 1,
      entry_price: 23295,
      exchange: "NFO",
      exit_price: 23368,
      fees: 92,
      hour: 9,
      minute: 41,
      pnl: 1825,
      price: 23295,
      quantity: 50,
      strategy: "Opening Range",
      symbol: "NIFTY",
    },
    {
      action: "BUY",
      daysAgo: 1,
      entry_price: 887,
      exchange: "NSE",
      exit_price: 878,
      fees: 47,
      hour: 13,
      minute: 36,
      pnl: -720,
      price: 887,
      quantity: 80,
      strategy: "Gap Fade",
      symbol: "SBIN",
    },
  ];

  return trades.map(makeTrade);
}

function isWithinDateRange(trade: JournalTrade, startDate?: string, endDate?: string): boolean {
  const tradeDate = trade.timestamp.slice(0, 10);
  if (startDate && tradeDate < startDate) return false;
  if (endDate && tradeDate > endDate) return false;
  return true;
}

export function getSampleJournalTrades(
  startDate?: string,
  endDate?: string,
  strategy?: string,
  limit = SAMPLE_LIMIT,
): JournalTrade[] {
  const strategyQuery = strategy?.trim().toLowerCase();

  return buildSampleJournalTrades()
    .filter((trade) => isWithinDateRange(trade, startDate, endDate))
    .filter((trade) =>
      strategyQuery ? trade.strategy.toLowerCase().includes(strategyQuery) : true,
    )
    .sort((a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime())
    .slice(0, limit);
}
