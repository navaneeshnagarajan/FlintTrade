/**
 * tradingviewTemplates.ts
 *
 * Pre-built TradingView alert webhook message templates for Indian F&O trading.
 *
 * Usage:
 *  1. In TradingView, open an alert and switch the message field to "JSON".
 *  2. Paste the `webhookMessage` string.
 *  3. Set the webhook URL to your OpenAlgo endpoint:
 *       http://<host>:5000/api/v1/strategy/webhook
 *  4. Add the optional Pine Script snippet to your indicator/strategy to trigger
 *     the alert at the right time.
 *
 * TradingView placeholders used across templates:
 *   {{ticker}}                — Exchange symbol (e.g. NIFTY, RELIANCE)
 *   {{exchange}}              — Exchange (e.g. NSE, BSE, MCX)
 *   {{close}}                 — Closing / current price
 *   {{open}}                  — Opening price of the bar
 *   {{high}}                  — High of the bar
 *   {{low}}                   — Low of the bar
 *   {{volume}}                — Bar volume
 *   {{time}}                  — Bar time (Unix timestamp string)
 *   {{timenow}}               — Current wall-clock time (Unix timestamp string)
 *   {{strategy.order.action}} — "buy" or "sell" from a strategy's order
 *   {{strategy.order.price}}  — Fill price from a strategy's order
 *   {{strategy.order.id}}     — Order ID label from the strategy
 *   {{interval}}              — Chart timeframe (e.g. "15", "D")
 */

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface TVAlertTemplate {
  /** Stable, URL-safe identifier. */
  id: string;
  /** Human-readable display name. */
  name: string;
  /** One-line description shown in the browser card. */
  description: string;
  /** Logical grouping for filter tabs. */
  category: "trend" | "momentum" | "volatility" | "options" | "custom";
  /**
   * Ready-to-paste JSON string for TradingView's alert webhook message field.
   * May contain TradingView dynamic placeholders (e.g. {{ticker}}).
   */
  webhookMessage: string;
  /**
   * Minimal Pine Script v5 snippet that fires the alert condition.
   * Provided for reference — paste this into a new indicator or strategy script.
   */
  pineSnippet?: string;
  /**
   * All TradingView dynamic placeholders present in `webhookMessage`.
   * Listed explicitly so the browser UI can highlight them.
   */
  placeholders: string[];
}

// ---------------------------------------------------------------------------
// Helper — keeps JSON tidy without a runtime dep
// ---------------------------------------------------------------------------

function json(obj: Record<string, unknown>): string {
  return JSON.stringify(obj, null, 2);
}

// ---------------------------------------------------------------------------
// Template catalogue
// ---------------------------------------------------------------------------

export const TV_ALERT_TEMPLATES: TVAlertTemplate[] = [
  // 1 ─ SuperTrend BUY / SELL ────────────────────────────────────────────────
  {
    id: "supertrend-buy-sell",
    name: "SuperTrend BUY / SELL",
    description:
      "Market order on every SuperTrend direction flip. Suitable for trending F&O underlying.",
    category: "trend",
    webhookMessage: json({
      action: "{{strategy.order.action}}",
      symbol: "{{ticker}}",
      exchange: "{{exchange}}",
      quantity: "75",
      price: "0",
      pricetype: "MARKET",
      product: "MIS",
      strategy: "TV-SuperTrend",
    }),
    pineSnippet: `// SuperTrend alert snippet — Pine Script v5
//@version=5
indicator("SuperTrend Alert", overlay=true)
atrPeriod = input.int(10, "ATR Period")
factor    = input.float(3.0, "Factor")
[_, direction] = ta.supertrend(factor, atrPeriod)
buySignal  = ta.crossunder(direction, 0)
sellSignal = ta.crossover(direction, 0)
alertcondition(buySignal,  "SuperTrend BUY",  "SuperTrend flipped UP — BUY")
alertcondition(sellSignal, "SuperTrend SELL", "SuperTrend flipped DOWN — SELL")`,
    placeholders: [
      "{{strategy.order.action}}",
      "{{ticker}}",
      "{{exchange}}",
    ],
  },

  // 2 ─ EMA Crossover 9/21 ───────────────────────────────────────────────────
  {
    id: "ema-crossover-9-21",
    name: "EMA Crossover 9 / 21",
    description:
      "Fires when the 9-period EMA crosses the 21-period EMA on any timeframe.",
    category: "trend",
    webhookMessage: json({
      action: "{{strategy.order.action}}",
      symbol: "{{ticker}}",
      exchange: "{{exchange}}",
      quantity: "50",
      price: "0",
      pricetype: "MARKET",
      product: "MIS",
      strategy: "TV-EMA-9-21",
      close: "{{close}}",
      time: "{{timenow}}",
    }),
    pineSnippet: `// EMA 9/21 crossover — Pine Script v5
//@version=5
indicator("EMA 9/21 Crossover", overlay=true)
ema9  = ta.ema(close, 9)
ema21 = ta.ema(close, 21)
bullCross = ta.crossover(ema9, ema21)
bearCross = ta.crossunder(ema9, ema21)
alertcondition(bullCross, "EMA Bull Cross", "EMA 9 crossed ABOVE EMA 21")
alertcondition(bearCross, "EMA Bear Cross", "EMA 9 crossed BELOW EMA 21")`,
    placeholders: [
      "{{strategy.order.action}}",
      "{{ticker}}",
      "{{exchange}}",
      "{{close}}",
      "{{timenow}}",
    ],
  },

  // 3 ─ RSI Overbought / Oversold ────────────────────────────────────────────
  {
    id: "rsi-ob-os",
    name: "RSI Overbought / Oversold",
    description:
      "Alert when 14-period RSI crosses 70 (overbought) or 30 (oversold).",
    category: "momentum",
    webhookMessage: json({
      action: "{{strategy.order.action}}",
      symbol: "{{ticker}}",
      exchange: "{{exchange}}",
      quantity: "50",
      price: "0",
      pricetype: "MARKET",
      product: "MIS",
      strategy: "TV-RSI",
      rsi_signal: "{{plot_0}}",
      close: "{{close}}",
    }),
    pineSnippet: `// RSI Overbought/Oversold — Pine Script v5
//@version=5
indicator("RSI OB/OS Alert", overlay=false)
rsiVal = ta.rsi(close, 14)
plot(rsiVal, "RSI", color.blue)
alertcondition(ta.crossunder(rsiVal, 30), "RSI Oversold",    "RSI crossed BELOW 30 — potential reversal UP")
alertcondition(ta.crossover(rsiVal,  70), "RSI Overbought",  "RSI crossed ABOVE 70 — potential reversal DOWN")`,
    placeholders: [
      "{{strategy.order.action}}",
      "{{ticker}}",
      "{{exchange}}",
      "{{close}}",
      "{{plot_0}}",
    ],
  },

  // 4 ─ MACD Signal Cross ────────────────────────────────────────────────────
  {
    id: "macd-signal-cross",
    name: "MACD Signal Cross",
    description:
      "Entry when the MACD line crosses the signal line (12/26/9 default).",
    category: "momentum",
    webhookMessage: json({
      action: "{{strategy.order.action}}",
      symbol: "{{ticker}}",
      exchange: "{{exchange}}",
      quantity: "50",
      price: "0",
      pricetype: "MARKET",
      product: "MIS",
      strategy: "TV-MACD",
      interval: "{{interval}}",
      close: "{{close}}",
      time: "{{time}}",
    }),
    pineSnippet: `// MACD Signal Cross — Pine Script v5
//@version=5
indicator("MACD Signal Cross Alert", overlay=false)
[macdLine, signalLine, _] = ta.macd(close, 12, 26, 9)
bullCross = ta.crossover(macdLine,  signalLine)
bearCross = ta.crossunder(macdLine, signalLine)
alertcondition(bullCross, "MACD Bull Cross", "MACD crossed ABOVE Signal — BUY")
alertcondition(bearCross, "MACD Bear Cross", "MACD crossed BELOW Signal — SELL")`,
    placeholders: [
      "{{strategy.order.action}}",
      "{{ticker}}",
      "{{exchange}}",
      "{{interval}}",
      "{{close}}",
      "{{time}}",
    ],
  },

  // 5 ─ Bollinger Band Breakout ──────────────────────────────────────────────
  {
    id: "bb-breakout",
    name: "Bollinger Band Breakout",
    description:
      "Fires when price closes outside the upper or lower Bollinger Band (20, 2.0).",
    category: "volatility",
    webhookMessage: json({
      action: "{{strategy.order.action}}",
      symbol: "{{ticker}}",
      exchange: "{{exchange}}",
      quantity: "50",
      price: "{{close}}",
      pricetype: "MARKET",
      product: "MIS",
      strategy: "TV-BB-Breakout",
      close: "{{close}}",
      high: "{{high}}",
      low: "{{low}}",
    }),
    pineSnippet: `// Bollinger Band Breakout — Pine Script v5
//@version=5
indicator("BB Breakout Alert", overlay=true)
[basis, upper, lower] = ta.bb(close, 20, 2.0)
alertcondition(close > upper, "BB Upper Break", "Price closed ABOVE upper Bollinger Band")
alertcondition(close < lower, "BB Lower Break", "Price closed BELOW lower Bollinger Band")`,
    placeholders: [
      "{{strategy.order.action}}",
      "{{ticker}}",
      "{{exchange}}",
      "{{close}}",
      "{{high}}",
      "{{low}}",
    ],
  },

  // 6 ─ VWAP Cross ───────────────────────────────────────────────────────────
  {
    id: "vwap-cross",
    name: "VWAP Cross",
    description:
      "Intraday alert when price crosses the daily VWAP. High-conviction for scalpers.",
    category: "trend",
    webhookMessage: json({
      action: "{{strategy.order.action}}",
      symbol: "{{ticker}}",
      exchange: "{{exchange}}",
      quantity: "75",
      price: "0",
      pricetype: "MARKET",
      product: "MIS",
      strategy: "TV-VWAP",
      close: "{{close}}",
      time: "{{timenow}}",
    }),
    pineSnippet: `// VWAP Cross — Pine Script v5
//@version=5
indicator("VWAP Cross Alert", overlay=true)
vwapVal  = ta.vwap(hlc3)
bullCross = ta.crossover(close,  vwapVal)
bearCross = ta.crossunder(close, vwapVal)
alertcondition(bullCross, "Price Above VWAP", "Price crossed ABOVE VWAP — bullish intraday")
alertcondition(bearCross, "Price Below VWAP", "Price crossed BELOW VWAP — bearish intraday")`,
    placeholders: [
      "{{strategy.order.action}}",
      "{{ticker}}",
      "{{exchange}}",
      "{{close}}",
      "{{timenow}}",
    ],
  },

  // 7 ─ Opening Range Breakout (ORB) ─────────────────────────────────────────
  {
    id: "orb-breakout",
    name: "Opening Range Breakout (ORB)",
    description:
      "Breakout above / below the first 15-minute candle range. Classic intraday setup.",
    category: "trend",
    webhookMessage: json({
      action: "{{strategy.order.action}}",
      symbol: "{{ticker}}",
      exchange: "{{exchange}}",
      quantity: "75",
      price: "0",
      pricetype: "MARKET",
      product: "MIS",
      strategy: "TV-ORB-15",
      close: "{{close}}",
      open: "{{open}}",
      time: "{{time}}",
    }),
    pineSnippet: `// Opening Range Breakout 15-min — Pine Script v5
//@version=5
indicator("ORB 15-min Alert", overlay=true)
// Capture the first 15-min candle's high and low (requires 15-min chart)
orbHigh = request.security(syminfo.tickerid, "15", high[1], lookahead=barmerge.lookahead_on)
orbLow  = request.security(syminfo.tickerid, "15", low[1],  lookahead=barmerge.lookahead_on)
alertcondition(ta.crossover(close, orbHigh),  "ORB Breakout UP",   "Price broke above 15-min ORB high")
alertcondition(ta.crossunder(close, orbLow),  "ORB Breakout DOWN", "Price broke below 15-min ORB low")`,
    placeholders: [
      "{{strategy.order.action}}",
      "{{ticker}}",
      "{{exchange}}",
      "{{close}}",
      "{{open}}",
      "{{time}}",
    ],
  },

  // 8 ─ Volume Spike ─────────────────────────────────────────────────────────
  {
    id: "volume-spike",
    name: "Volume Spike Alert",
    description:
      "Triggers when current bar volume exceeds 2× the 20-bar average — potential breakout signal.",
    category: "momentum",
    webhookMessage: json({
      action: "BUY",
      symbol: "{{ticker}}",
      exchange: "{{exchange}}",
      quantity: "50",
      price: "0",
      pricetype: "MARKET",
      product: "MIS",
      strategy: "TV-VolumeSpike",
      volume: "{{volume}}",
      close: "{{close}}",
      time: "{{timenow}}",
    }),
    pineSnippet: `// Volume Spike — Pine Script v5
//@version=5
indicator("Volume Spike Alert", overlay=false)
avgVol   = ta.sma(volume, 20)
isSpike  = volume > avgVol * 2.0
alertcondition(isSpike, "Volume Spike", "Volume exceeded 2× 20-bar average — possible breakout")`,
    placeholders: [
      "{{ticker}}",
      "{{exchange}}",
      "{{volume}}",
      "{{close}}",
      "{{timenow}}",
    ],
  },

  // 9 ─ Straddle Entry (ATM Options) ─────────────────────────────────────────
  {
    id: "straddle-atm-entry",
    name: "Straddle Entry — ATM Options",
    description:
      "Simultaneous BUY of ATM CE and PE for a straddle. Set symbol to the index (e.g. NIFTY).",
    category: "options",
    webhookMessage: json({
      action: "BUY",
      symbol: "{{ticker}}",
      exchange: "NFO",
      quantity: "50",
      price: "0",
      pricetype: "MARKET",
      product: "MIS",
      strategy: "TV-Straddle",
      option_type: "STRADDLE",
      expiry: "WEEKLY",
      strike: "ATM",
      close: "{{close}}",
      time: "{{timenow}}",
    }),
    pineSnippet: `// Straddle Entry Trigger — Pine Script v5
//@version=5
// Fires at 09:20 on first bar after market open (15-min chart)
indicator("Straddle Entry Trigger", overlay=true)
isEntryTime = (hour == 9 and minute == 20)
isFirstBar  = isEntryTime and not isEntryTime[1]
alertcondition(isFirstBar, "Straddle Entry", "Time-based straddle entry at 09:20")`,
    // exchange is hardcoded to "NFO" for Indian options — not a TV placeholder
    placeholders: [
      "{{ticker}}",
      "{{close}}",
      "{{timenow}}",
    ],
  },

  // 10 ─ Custom JSON (user-editable template) ───────────────────────────────
  {
    id: "custom-json",
    name: "Custom JSON Template",
    description:
      "Blank scaffold — edit to build your own webhook payload. All common placeholders included.",
    category: "custom",
    webhookMessage: json({
      action: "{{strategy.order.action}}",
      symbol: "{{ticker}}",
      exchange: "{{exchange}}",
      quantity: "1",
      price: "{{strategy.order.price}}",
      pricetype: "LIMIT",
      product: "MIS",
      strategy: "MY-STRATEGY",
      order_id: "{{strategy.order.id}}",
      close: "{{close}}",
      open: "{{open}}",
      high: "{{high}}",
      low: "{{low}}",
      volume: "{{volume}}",
      interval: "{{interval}}",
      time: "{{timenow}}",
    }),
    pineSnippet: undefined,
    placeholders: [
      "{{strategy.order.action}}",
      "{{ticker}}",
      "{{exchange}}",
      "{{strategy.order.price}}",
      "{{strategy.order.id}}",
      "{{close}}",
      "{{open}}",
      "{{high}}",
      "{{low}}",
      "{{volume}}",
      "{{interval}}",
      "{{timenow}}",
    ],
  },
];

// ---------------------------------------------------------------------------
// Utility helpers used by AlertTemplateBrowser
// ---------------------------------------------------------------------------

/** All distinct categories present in the template list. */
export const TV_TEMPLATE_CATEGORIES = [
  ...new Set(TV_ALERT_TEMPLATES.map((t) => t.category)),
] as const;

/** Look up a single template by id. Returns undefined if not found. */
export function getTemplateById(id: string): TVAlertTemplate | undefined {
  return TV_ALERT_TEMPLATES.find((t) => t.id === id);
}

/** Filter templates by category. Pass undefined to get all. */
export function filterTemplatesByCategory(
  category?: TVAlertTemplate["category"]
): TVAlertTemplate[] {
  if (!category) return TV_ALERT_TEMPLATES;
  return TV_ALERT_TEMPLATES.filter((t) => t.category === category);
}
