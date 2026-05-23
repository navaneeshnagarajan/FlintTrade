/**
 * etfs.ts
 *
 * Static universe of Indian ETFs tracked in the Invest → ETF tab.
 * Exchange is always NSE (EQ segment) for these symbols.
 * Expense ratios are approximate annual TER values (as of 2025).
 */

export interface EtfInfo {
  symbol: string;
  name: string;
  underlying: string;
  expenseRatio: number;
  exchange: "NSE" | "BSE";
}

export const ETF_UNIVERSE: EtfInfo[] = [
  {
    symbol: "NIFTYBEES",
    name: "Nippon India Nifty 50 BeES",
    underlying: "NIFTY 50",
    expenseRatio: 0.04,
    exchange: "NSE",
  },
  {
    symbol: "BANKBEES",
    name: "Nippon India Bank BeES",
    underlying: "NIFTY BANK",
    expenseRatio: 0.19,
    exchange: "NSE",
  },
  {
    symbol: "JUNIORBEES",
    name: "Nippon India Junior BeES",
    underlying: "NIFTY NEXT 50",
    expenseRatio: 0.19,
    exchange: "NSE",
  },
  {
    symbol: "GOLDBEES",
    name: "Nippon India Gold BeES",
    underlying: "Gold",
    expenseRatio: 0.79,
    exchange: "NSE",
  },
  {
    symbol: "LIQUIDBEES",
    name: "Nippon India Liquid BeES",
    underlying: "Liquid",
    expenseRatio: 0.69,
    exchange: "NSE",
  },
  {
    symbol: "ITBEES",
    name: "Nippon India IT BeES",
    underlying: "NIFTY IT",
    expenseRatio: 0.35,
    exchange: "NSE",
  },
  {
    symbol: "PHARMABEES",
    name: "Nippon India Pharma BeES",
    underlying: "NIFTY PHARMA",
    expenseRatio: 0.39,
    exchange: "NSE",
  },
  {
    symbol: "CPSEETF",
    name: "Nippon India CPSE ETF",
    underlying: "CPSE Index",
    expenseRatio: 0.07,
    exchange: "NSE",
  },
  {
    symbol: "SETFNIF50",
    name: "SBI Nifty 50 ETF",
    underlying: "NIFTY 50",
    expenseRatio: 0.07,
    exchange: "NSE",
  },
  {
    symbol: "MAFANG",
    name: "Mirae Asset FANG+ ETF",
    underlying: "NYSE FANG+",
    expenseRatio: 0.51,
    exchange: "NSE",
  },
];
