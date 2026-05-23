/**
 * contextTips.ts — Registry of contextual education tips.
 *
 * Tips appear based on what the user is currently looking at (widget, route, action).
 * Each tip is difficulty-gated so beginners see beginner tips, intermediates see
 * beginner + intermediate, and advanced users see all.
 *
 * Triggers follow the convention:
 *   "widget:<widgetName>"   — shown inside a specific Dockview widget
 *   "route:<routeName>"     — shown on a route page
 *   "action:<actionName>"   — shown after a user action (first-order, etc.)
 */

import type { SkillLevel } from "@/types/skill";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface ContextTip {
  id: string;
  trigger: string;
  title: string;
  /** Plain text content (no markdown rendering needed for the card) */
  content: string;
  difficulty: SkillLevel;
  category: "options" | "technical" | "fundamental" | "risk" | "tax";
  /** Deep link into /learn for further reading */
  learnMoreUrl?: string;
  dismissable: boolean;
}

// ---------------------------------------------------------------------------
// Tip registry
// ---------------------------------------------------------------------------

export const CONTEXT_TIPS: readonly ContextTip[] = [
  // ── Options (10) ──────────────────────────────────────────────────────────
  {
    id: "options-what-is-option-chain",
    trigger: "widget:optionchain",
    title: "What is an Option Chain?",
    content:
      "An option chain shows all available Call and Put contracts for a symbol, organized by strike price and expiry. Calls are on the left, Puts on the right, with the ATM (At The Money) strike highlighted in the center. Use it to compare premiums, OI, and Greeks across strikes.",
    difficulty: "beginner",
    category: "options",
    learnMoreUrl: "/learn",
    dismissable: true,
  },
  {
    id: "options-reading-greeks",
    trigger: "widget:greeks",
    title: "What are the Greeks?",
    content:
      "Greeks measure how an option's price changes with market factors. Delta = price sensitivity to underlying movement. Gamma = rate of Delta change. Theta = daily time decay (cost of holding). Vega = sensitivity to implied volatility changes. Together they quantify your portfolio's risk exposure.",
    difficulty: "beginner",
    category: "options",
    learnMoreUrl: "/learn",
    dismissable: true,
  },
  {
    id: "options-understanding-iv",
    trigger: "widget:optionchain",
    title: "Understanding Implied Volatility (IV)",
    content:
      "IV represents the market's expectation of future price movement. High IV means options are expensive (big expected moves). Low IV means options are cheap (calm market expected). IV typically spikes before events like earnings or budget and drops after — this is called IV crush.",
    difficulty: "intermediate",
    category: "options",
    learnMoreUrl: "/learn",
    dismissable: true,
  },
  {
    id: "options-straddle-basics",
    trigger: "widget:straddle",
    title: "Straddle Basics",
    content:
      "A straddle involves buying (or selling) both a Call and Put at the same strike price. Long straddle profits from big moves in either direction. Short straddle profits when the market stays range-bound and options decay. The breakeven points are strike plus/minus total premium paid.",
    difficulty: "intermediate",
    category: "options",
    learnMoreUrl: "/learn",
    dismissable: true,
  },
  {
    id: "options-iron-condor",
    trigger: "widget:optionchain",
    title: "Iron Condor Explained",
    content:
      "An iron condor combines a bull put spread and bear call spread. You sell an OTM Put and Call, then buy further OTM options as hedges. Max profit is the net premium collected. Max loss is limited to the spread width minus premium. It profits when the market stays within your short strikes.",
    difficulty: "advanced",
    category: "options",
    learnMoreUrl: "/learn",
    dismissable: true,
  },
  {
    id: "options-max-pain",
    trigger: "widget:optionchain",
    title: "Max Pain Concept",
    content:
      "Max Pain is the strike price where the maximum number of options (Calls + Puts) expire worthless, causing the most financial loss to option buyers. Markets often gravitate toward max pain near expiry. It is a useful reference point but not a guaranteed predictor.",
    difficulty: "intermediate",
    category: "options",
    learnMoreUrl: "/learn",
    dismissable: true,
  },
  {
    id: "options-oi-analysis",
    trigger: "widget:oichart",
    title: "Open Interest (OI) Analysis",
    content:
      "OI is the total number of outstanding contracts. Rising OI + rising price = Long Build Up (bullish). Rising OI + falling price = Short Build Up (bearish). Falling OI + rising price = Short Covering. Falling OI + falling price = Long Unwinding. OI change is more informative than absolute OI.",
    difficulty: "intermediate",
    category: "options",
    learnMoreUrl: "/learn",
    dismissable: true,
  },
  {
    id: "options-expiry-behavior",
    trigger: "widget:optionchain",
    title: "Expiry Day Behavior",
    content:
      "On expiry day, theta decay accelerates dramatically — options lose value rapidly. ATM options are most affected. Gamma risk spikes near ATM strikes, causing sudden directional moves. Many traders avoid holding positions into expiry unless they have a defined-risk strategy.",
    difficulty: "advanced",
    category: "options",
    learnMoreUrl: "/learn",
    dismissable: true,
  },
  {
    id: "options-theta-decay",
    trigger: "widget:greeks",
    title: "Theta Decay — Time is Money",
    content:
      "Theta measures how much an option loses per day from time decay alone. ATM options have the highest theta. Decay accelerates in the last week before expiry. Option sellers collect theta as profit; option buyers pay it as a cost. Weekly options decay faster than monthly ones.",
    difficulty: "beginner",
    category: "options",
    learnMoreUrl: "/learn",
    dismissable: true,
  },
  {
    id: "options-pcr",
    trigger: "widget:optionchain",
    title: "Put-Call Ratio (PCR)",
    content:
      "PCR = Put OI divided by Call OI. PCR > 1 suggests bearish sentiment (more puts). PCR < 1 suggests bullish sentiment (more calls). Extreme readings (above 1.5 or below 0.5) can signal contrarian reversals. Track PCR change over the day for directional clues.",
    difficulty: "beginner",
    category: "options",
    learnMoreUrl: "/learn",
    dismissable: true,
  },

  // ── Technical (8) ─────────────────────────────────────────────────────────
  {
    id: "tech-candlestick-reading",
    trigger: "widget:chart",
    title: "Reading Candlestick Charts",
    content:
      "Each candle shows Open, High, Low, Close for a time period. Green/hollow = close above open (bullish). Red/filled = close below open (bearish). Long wicks show rejection. Patterns like Doji (indecision), Hammer (reversal), and Engulfing (momentum shift) help predict next moves.",
    difficulty: "beginner",
    category: "technical",
    learnMoreUrl: "/learn",
    dismissable: true,
  },
  {
    id: "tech-support-resistance",
    trigger: "widget:chart",
    title: "Support and Resistance Levels",
    content:
      "Support is a price level where buying interest prevents further decline. Resistance is where selling pressure prevents further rise. These levels form from previous highs/lows, round numbers, and high-volume areas. A break above resistance often becomes new support, and vice versa.",
    difficulty: "beginner",
    category: "technical",
    learnMoreUrl: "/learn",
    dismissable: true,
  },
  {
    id: "tech-vwap",
    trigger: "widget:chart",
    title: "VWAP — Volume Weighted Average Price",
    content:
      "VWAP is the average price weighted by volume, reset daily at market open. Institutional traders use it as a benchmark. Price above VWAP = bullish bias. Price below VWAP = bearish bias. Mean reversion strategies buy below VWAP and sell above it during range-bound sessions.",
    difficulty: "intermediate",
    category: "technical",
    learnMoreUrl: "/learn",
    dismissable: true,
  },
  {
    id: "tech-rsi-divergence",
    trigger: "widget:chart",
    title: "RSI Divergence",
    content:
      "RSI (Relative Strength Index) ranges from 0-100. Above 70 = overbought, below 30 = oversold. Divergence occurs when price makes a new high but RSI does not (bearish divergence) or price makes a new low but RSI does not (bullish divergence) — signaling a potential reversal.",
    difficulty: "intermediate",
    category: "technical",
    learnMoreUrl: "/learn",
    dismissable: true,
  },
  {
    id: "tech-ma-crossovers",
    trigger: "widget:chart",
    title: "Moving Average Crossovers",
    content:
      "When a shorter-period MA (e.g., 9 EMA) crosses above a longer one (e.g., 21 EMA), it signals bullish momentum — a golden cross. The reverse is a death cross (bearish). Common pairs: 9/21 for intraday, 50/200 for positional. Avoid crossover signals in sideways markets.",
    difficulty: "beginner",
    category: "technical",
    learnMoreUrl: "/learn",
    dismissable: true,
  },
  {
    id: "tech-volume-analysis",
    trigger: "widget:chart",
    title: "Volume Analysis",
    content:
      "Volume confirms price moves. Rising price + rising volume = strong trend. Rising price + falling volume = weakening trend (potential reversal). Volume spikes at support/resistance breakouts validate the move. Always check if volume supports the price action before entering a trade.",
    difficulty: "intermediate",
    category: "technical",
    learnMoreUrl: "/learn",
    dismissable: true,
  },
  {
    id: "tech-bollinger-bands",
    trigger: "widget:chart",
    title: "Bollinger Bands",
    content:
      "Bollinger Bands plot a moving average with upper and lower bands at 2 standard deviations. When bands squeeze (narrow), a big move is coming. Price touching the upper band does not mean sell — in strong trends, price walks the band. A squeeze followed by expansion signals the breakout direction.",
    difficulty: "intermediate",
    category: "technical",
    learnMoreUrl: "/learn",
    dismissable: true,
  },
  {
    id: "tech-chart-patterns",
    trigger: "widget:chart",
    title: "Chart Patterns",
    content:
      "Common patterns: Head and Shoulders (reversal), Double Top/Bottom (reversal), Triangle (continuation or reversal), Flag/Pennant (continuation). Pattern targets are measured by the pattern height projected from the breakout point. Volume should confirm the breakout for higher reliability.",
    difficulty: "advanced",
    category: "technical",
    learnMoreUrl: "/learn",
    dismissable: true,
  },

  // ── Fundamental (5) ───────────────────────────────────────────────────────
  {
    id: "fund-pe-ratio",
    trigger: "route:invest",
    title: "PE Ratio — Price to Earnings",
    content:
      "PE ratio = Stock Price / Earnings Per Share. It tells you how much investors pay per rupee of earnings. A high PE may mean overvalued or high growth expectations. A low PE may mean undervalued or declining business. Compare PE within the same sector, not across sectors.",
    difficulty: "beginner",
    category: "fundamental",
    learnMoreUrl: "/learn",
    dismissable: true,
  },
  {
    id: "fund-market-cap",
    trigger: "route:invest",
    title: "Market Capitalization Explained",
    content:
      "Market cap = Share Price x Total Shares Outstanding. Large cap (> 20,000 Cr): stable, lower risk. Mid cap (5,000-20,000 Cr): growth potential, moderate risk. Small cap (< 5,000 Cr): high growth potential, high risk. SEBI categorizes funds by market cap for mutual fund classification.",
    difficulty: "beginner",
    category: "fundamental",
    learnMoreUrl: "/learn",
    dismissable: true,
  },
  {
    id: "fund-roe-roce",
    trigger: "route:invest",
    title: "ROE and ROCE",
    content:
      "ROE (Return on Equity) = Net Income / Shareholder Equity. Measures how efficiently a company uses shareholder money. ROCE (Return on Capital Employed) includes debt. Consistently high ROE (> 15%) and ROCE (> 20%) suggest a well-managed, profitable business. Look for trends over 5+ years.",
    difficulty: "intermediate",
    category: "fundamental",
    learnMoreUrl: "/learn",
    dismissable: true,
  },
  {
    id: "fund-dividend-yield",
    trigger: "route:invest",
    title: "Dividend Yield",
    content:
      "Dividend yield = Annual Dividend / Share Price. A 3% yield means you earn 3 rupees per 100 invested, annually. High-yield stocks provide regular income but may have limited growth. Dividend aristocrats (consistent dividend raisers) are valued by income investors. Dividends are taxable above 5,000 per year.",
    difficulty: "beginner",
    category: "fundamental",
    learnMoreUrl: "/learn",
    dismissable: true,
  },
  {
    id: "fund-sector-rotation",
    trigger: "route:invest",
    title: "Sector Rotation",
    content:
      "Different sectors outperform at different stages of the economic cycle. Early recovery: financials, consumer discretionary. Expansion: technology, industrials. Late cycle: energy, materials. Recession: healthcare, utilities, consumer staples. Tracking sector rotation helps time entry into sectoral funds.",
    difficulty: "advanced",
    category: "fundamental",
    learnMoreUrl: "/learn",
    dismissable: true,
  },

  // ── Risk (4) ──────────────────────────────────────────────────────────────
  {
    id: "risk-position-sizing",
    trigger: "widget:scalper",
    title: "Position Sizing Basics",
    content:
      "Never risk more than 1-2% of your capital on a single trade. Calculate position size as: Risk Amount / (Entry Price - Stop Loss). For example, with 1L capital and 1% risk (1,000), if your stop is 50 points away, trade a max of 20 shares. This prevents any single loss from devastating your account.",
    difficulty: "beginner",
    category: "risk",
    learnMoreUrl: "/learn",
    dismissable: true,
  },
  {
    id: "risk-stop-loss-types",
    trigger: "widget:scalper",
    title: "Stop-Loss Types",
    content:
      "Fixed SL: set at a specific price (e.g., 2% below entry). Trailing SL: moves up with price, locks in profits. ATR-based SL: set at 1.5-2x ATR distance — adapts to volatility. Time-based SL: exit if trade does not move in your favor within N candles. Always place SL before entering a trade.",
    difficulty: "beginner",
    category: "risk",
    learnMoreUrl: "/learn",
    dismissable: true,
  },
  {
    id: "risk-reward-ratio",
    trigger: "widget:scalper",
    title: "Risk-Reward Ratio",
    content:
      "Risk-reward ratio = Potential Loss / Potential Gain. A 1:2 ratio means you risk 100 to make 200. Even with a 40% win rate, a 1:2 ratio is profitable over time: (0.4 x 200) - (0.6 x 100) = +20 per trade average. Never take trades below 1:1.5 ratio. Asymmetric payoffs are the edge.",
    difficulty: "intermediate",
    category: "risk",
    learnMoreUrl: "/learn",
    dismissable: true,
  },
  {
    id: "risk-diversification",
    trigger: "widget:dashboard",
    title: "Portfolio Diversification",
    content:
      "Do not put all your capital in one stock, sector, or asset class. Spread across large cap, mid cap, debt, and gold. For F&O, diversify across indices (NIFTY, BANKNIFTY) and strategies (directional + non-directional). Correlation matters — two banking stocks are not diversification.",
    difficulty: "beginner",
    category: "risk",
    learnMoreUrl: "/learn",
    dismissable: true,
  },

  // ── Tax (3) ───────────────────────────────────────────────────────────────
  {
    id: "tax-stcg-ltcg",
    trigger: "route:invest",
    title: "STCG vs LTCG — India",
    content:
      "For equity: holding < 12 months = Short Term Capital Gains taxed at 20%. Holding > 12 months = Long Term Capital Gains taxed at 12.5% above 1.25L exemption. For debt funds: all gains are taxed at your income tax slab rate regardless of holding period (post April 2023 rules).",
    difficulty: "beginner",
    category: "tax",
    learnMoreUrl: "/learn",
    dismissable: true,
  },
  {
    id: "tax-fno-business-income",
    trigger: "route:trade",
    title: "F&O Tax Treatment",
    content:
      "F&O profits/losses in India are treated as business income (not capital gains). You must file ITR-3 or ITR-4. Turnover = absolute sum of all profits and losses. If turnover < 2 Cr and profit > 6% of turnover, you can use presumptive taxation (44AD). Losses can be carried forward for 8 years.",
    difficulty: "intermediate",
    category: "tax",
    learnMoreUrl: "/learn",
    dismissable: true,
  },
  {
    id: "tax-loss-harvesting",
    trigger: "route:invest",
    title: "Tax-Loss Harvesting",
    content:
      "Sell losing positions before year-end to book losses that offset gains, reducing your tax bill. For equity: short-term losses offset both STCG and LTCG. For F&O: business losses offset business income. Reinvest in similar (not identical) assets to maintain market exposure while saving tax.",
    difficulty: "advanced",
    category: "tax",
    learnMoreUrl: "/learn",
    dismissable: true,
  },
] as const;

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** All unique categories in the registry */
export const TIP_CATEGORIES = [
  ...new Set(CONTEXT_TIPS.map((t) => t.category)),
] as const;

/** Get all tips matching a trigger pattern */
export function getTipsForTrigger(trigger: string): readonly ContextTip[] {
  return CONTEXT_TIPS.filter((t) => t.trigger === trigger);
}

/** Get all tips for a category */
export function getTipsByCategory(
  category: ContextTip["category"],
): readonly ContextTip[] {
  return CONTEXT_TIPS.filter((t) => t.category === category);
}

/**
 * Filter tips visible to a given skill level.
 * Beginner sees beginner only.
 * Intermediate sees beginner + intermediate.
 * Advanced sees all.
 */
export function filterTipsByLevel(
  tips: readonly ContextTip[],
  level: SkillLevel,
): readonly ContextTip[] {
  const allowed: Set<SkillLevel> = new Set();
  allowed.add("beginner");
  if (level === "intermediate" || level === "advanced") allowed.add("intermediate");
  if (level === "advanced") allowed.add("advanced");
  return tips.filter((t) => allowed.has(t.difficulty));
}
