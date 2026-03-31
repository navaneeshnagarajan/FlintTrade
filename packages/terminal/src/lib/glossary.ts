/**
 * glossary.ts — Financial term definitions for beginner-friendly tooltips.
 *
 * Used by <GlossaryTooltip> to show plain-English definitions on hover.
 * Keep definitions concise (1-2 sentences) and jargon-free where possible.
 */

export const GLOSSARY: Record<string, string> = {
  "LTCG":
    "Long Term Capital Gains — profit from selling equity held over 12 months. Taxed at 12.5% above \u20b91.25 lakh.",
  "STCG":
    "Short Term Capital Gains — profit from equity held under 12 months. Taxed at 20%.",
  "STT":
    "Securities Transaction Tax — charged by the exchange on every trade.",
  "NAV":
    "Net Asset Value — the per-unit price of a mutual fund.",
  "XIRR":
    "Extended Internal Rate of Return — measures annualized return considering irregular cash flows (SIP dates).",
  "SIP":
    "Systematic Investment Plan — auto-invest a fixed amount monthly into mutual funds.",
  "VIX":
    "India VIX — measures expected market volatility over 30 days. High VIX = high fear.",
  "F&O":
    "Futures & Options — derivative instruments for hedging or speculation.",
  "OI":
    "Open Interest — total outstanding derivative contracts. Rising OI = new positions being created.",
  "IV":
    "Implied Volatility — market's expectation of future price movement, derived from option prices.",
  "PCR":
    "Put-Call Ratio — ratio of put OI to call OI. PCR > 1 = bearish sentiment.",
  "ATM":
    "At The Money — option strike price closest to current market price.",
  "ITM":
    "In The Money — option with intrinsic value (call: strike < market, put: strike > market).",
  "OTM":
    "Out of The Money — option with no intrinsic value.",
  "Greeks":
    "Option sensitivity measures: Delta (price), Gamma (delta change), Theta (time decay), Vega (volatility).",
  "GEX":
    "Gamma Exposure — aggregate dealer gamma. Positive GEX = market makers dampen moves.",
  "Max Pain":
    "Strike price where option buyers lose the most money. Market often gravitates here near expiry.",
  "VWAP":
    "Volume Weighted Average Price — average price weighted by volume. Key intraday reference.",
  "RSI":
    "Relative Strength Index — momentum oscillator (0-100). Above 70 = overbought, below 30 = oversold.",
  "MACD":
    "Moving Average Convergence Divergence — trend-following momentum indicator.",
  "MIS":
    "Margin Intraday Square-off — intraday position that must be closed before market end.",
  "CNC":
    "Cash and Carry — delivery trade where shares are held in demat account.",
  "NRML":
    "Normal — overnight F&O position carried to next day.",
  "PE Ratio":
    "Price to Earnings — stock price divided by earnings per share. Lower = potentially cheaper.",
  "ROE":
    "Return on Equity — net income / shareholder equity. Higher = better capital efficiency.",
  "ROCE":
    "Return on Capital Employed — measures how efficiently a company uses its total capital.",
  "Scalper":
    "Trader who makes many quick trades for small profits, typically holding positions for seconds to minutes.",
  "Margin":
    "Money required to open a leveraged position. Not the same as cost basis.",
  "P&L":
    "Profit and Loss — the net gain or loss on your positions for a given period.",
  "Day P&L":
    "Profit and Loss for the current trading day based on unrealised position values.",
};
