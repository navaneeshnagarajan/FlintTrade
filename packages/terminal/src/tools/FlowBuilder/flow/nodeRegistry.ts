/**
 * nodeRegistry.ts — Node category definitions and lookup maps.
 *
 * Single source of truth for all 54 flow builder nodes.
 * Absorbed from openalgo-flow node registry.
 */

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type NodeCategoryId =
  | "triggers"
  | "actions"
  | "conditions"
  | "logic"
  | "data"
  | "websocket"
  | "risk"
  | "utilities";

export interface NodeDef {
  type: string;
  label: string;
  description: string;
  configFields?: string[];
}

export interface NodeCategoryDef {
  id: NodeCategoryId;
  label: string;
  color: string;
  nodes: NodeDef[];
}

// ---------------------------------------------------------------------------
// Category colour map (design tokens: matches task spec)
// ---------------------------------------------------------------------------

export const CATEGORY_COLORS: Record<NodeCategoryId, string> = {
  triggers: "#f59e0b",   // amber
  actions: "#22c55e",    // green (orders)
  conditions: "#818cf8", // indigo
  logic: "#ec4899",      // pink
  data: "#38bdf8",       // sky blue
  websocket: "#34d399",  // teal/emerald
  risk: "#f97316",       // orange
  utilities: "#a78bfa",  // violet
};

// ---------------------------------------------------------------------------
// Node registry
// ---------------------------------------------------------------------------

export const NODE_CATEGORIES: NodeCategoryDef[] = [
  {
    id: "triggers",
    label: "Triggers",
    color: CATEGORY_COLORS.triggers,
    nodes: [
      { type: "start", label: "Start", description: "Manual or scheduled entry point", configFields: [] },
      { type: "priceAlert", label: "Price Alert", description: "Trigger on price threshold breach", configFields: ["symbol", "exchange", "threshold", "operator"] },
      { type: "webhookTrigger", label: "Webhook Trigger", description: "TradingView / Chartink webhook", configFields: ["path"] },
      { type: "httpRequest", label: "HTTP Request", description: "External HTTP event trigger", configFields: ["url", "method"] },
    ],
  },
  {
    id: "actions",
    label: "Orders",
    color: CATEGORY_COLORS.actions,
    nodes: [
      { type: "placeOrder", label: "Place Order", description: "Market / limit / SL order via OpenAlgo", configFields: ["symbol", "exchange", "qty", "product", "side", "type", "price"] },
      { type: "smartOrder", label: "Smart Order", description: "Position-aware order with quantity management", configFields: ["symbol", "exchange", "qty", "product", "side", "type", "positionSize"] },
      { type: "optionsOrder", label: "Options Order", description: "Single options order", configFields: ["symbol", "exchange", "qty", "product", "side", "type", "expiry", "strike", "optionType"] },
      { type: "optionsMultiOrder", label: "Options Multi Order", description: "Basket of options orders", configFields: [] },
      { type: "basketOrder", label: "Basket Order", description: "Multi-leg equity basket", configFields: [] },
      { type: "splitOrder", label: "Split Order", description: "Break large order into chunks", configFields: ["symbol", "exchange", "qty", "chunks"] },
      { type: "cancelOrder", label: "Cancel Order", description: "Cancel a specific order", configFields: ["orderId"] },
      { type: "cancelAllOrders", label: "Cancel All Orders", description: "Cancel all open orders", configFields: [] },
      { type: "modifyOrder", label: "Modify Order", description: "Change price, qty, or type", configFields: ["orderId", "price", "qty"] },
      { type: "closePositions", label: "Close Positions", description: "Square off all open positions", configFields: [] },
    ],
  },
  {
    id: "conditions",
    label: "Conditions",
    color: CATEGORY_COLORS.conditions,
    nodes: [
      { type: "positionCheck", label: "Position Check", description: "Branch on open position state", configFields: ["symbol"] },
      { type: "fundCheck", label: "Fund Check", description: "Gate on available margin", configFields: ["minFunds"] },
      { type: "timeWindow", label: "Time Window", description: "Allow flow only within market hours", configFields: ["start", "end"] },
      { type: "timeCondition", label: "Time Condition", description: "Specific time-based gate", configFields: ["time"] },
      { type: "priceCondition", label: "Price Condition", description: "If price > / < / = threshold", configFields: ["operator", "threshold"] },
    ],
  },
  {
    id: "logic",
    label: "Logic Gates",
    color: CATEGORY_COLORS.logic,
    nodes: [
      { type: "andGate", label: "AND Gate", description: "All inputs must be true", configFields: [] },
      { type: "orGate", label: "OR Gate", description: "Any input must be true", configFields: [] },
      { type: "notGate", label: "NOT Gate", description: "Invert boolean signal", configFields: [] },
      { type: "ifElse", label: "If / Else", description: "Two-branch conditional", configFields: [] },
      { type: "switch", label: "Switch", description: "Multi-branch selector on a named variable", configFields: ["variable"] },
      { type: "loop", label: "Loop", description: "Repeat N times or while condition holds", configFields: ["count"] },
      { type: "schedule", label: "Schedule", description: "Cron-style timed trigger within a flow", configFields: ["cron"] },
    ],
  },
  {
    id: "data",
    label: "Data",
    color: CATEGORY_COLORS.data,
    nodes: [
      { type: "getQuote", label: "Get Quote", description: "LTP, bid/ask, OHLC", configFields: ["symbol", "exchange"] },
      { type: "getDepth", label: "Get Depth", description: "50-level order book", configFields: ["symbol", "exchange"] },
      { type: "getOrderStatus", label: "Order Status", description: "Check order fill state", configFields: [] },
      { type: "history", label: "History", description: "OHLCV historical bars", configFields: ["symbol", "exchange", "interval"] },
      { type: "openPosition", label: "Open Position", description: "Get current position details", configFields: ["symbol"] },
      { type: "expiry", label: "Expiry", description: "Options expiry lookup", configFields: ["symbol", "exchange"] },
      { type: "intervals", label: "Intervals", description: "Available data intervals", configFields: [] },
      { type: "multiQuotes", label: "Multi Quotes", description: "Bulk quotes for multiple symbols", configFields: [] },
      { type: "symbol", label: "Symbol", description: "Resolve symbol across exchanges", configFields: ["symbol", "exchange"] },
      { type: "optionSymbol", label: "Option Symbol", description: "Options chain symbol resolver", configFields: ["symbol", "exchange", "expiry", "strike", "optionType"] },
      { type: "orderBook", label: "Order Book", description: "Get full order book", configFields: [] },
      { type: "tradeBook", label: "Trade Book", description: "Get executed trades", configFields: [] },
      { type: "positionBook", label: "Position Book", description: "All current positions", configFields: [] },
      { type: "syntheticFuture", label: "Synthetic Future", description: "Construct synthetic F&O", configFields: ["symbol", "exchange", "expiry"] },
      { type: "optionChain", label: "Option Chain", description: "Full chain with Greeks", configFields: ["symbol", "exchange", "expiry"] },
      { type: "holidays", label: "Holidays", description: "Market holiday calendar", configFields: [] },
      { type: "timings", label: "Timings", description: "Exchange trading hours", configFields: [] },
    ],
  },
  {
    id: "websocket",
    label: "WebSocket",
    color: CATEGORY_COLORS.websocket,
    nodes: [
      { type: "subscribeLtp", label: "Subscribe LTP", description: "Real-time last traded price", configFields: ["symbol", "exchange"] },
      { type: "subscribeQuote", label: "Subscribe Quote", description: "Real-time quote stream", configFields: ["symbol", "exchange"] },
      { type: "subscribeDepth", label: "Subscribe Depth", description: "50-level depth stream", configFields: ["symbol", "exchange"] },
      { type: "unsubscribe", label: "Unsubscribe", description: "Stop streaming for symbol", configFields: ["symbol", "exchange"] },
    ],
  },
  {
    id: "risk",
    label: "Account",
    color: CATEGORY_COLORS.risk,
    nodes: [
      { type: "holdings", label: "Holdings", description: "Delivery / long-term positions", configFields: [] },
      { type: "funds", label: "Funds", description: "Account balance and margins", configFields: [] },
      { type: "margin", label: "Margin", description: "Calculate required margin", configFields: ["symbol", "exchange", "qty", "product"] },
    ],
  },
  {
    id: "utilities",
    label: "Integration",
    color: CATEGORY_COLORS.utilities,
    nodes: [
      { type: "telegramAlert", label: "Telegram Alert", description: "Send signal to Telegram bot", configFields: ["message"] },
      { type: "webhookAlert", label: "Webhook (Outgoing)", description: "POST JSON payload to any URL", configFields: ["url"] },
      { type: "emailAlert", label: "Email Alert", description: "Send email notification", configFields: ["to", "subject"] },
      { type: "delay", label: "Delay", description: "Wait N seconds before next node", configFields: ["seconds"] },
      { type: "waitUntil", label: "Wait Until", description: "Pause until condition is met", configFields: [] },
      { type: "group", label: "Group", description: "Bundle nodes into a sub-flow", configFields: ["name"] },
      { type: "variable", label: "Variable", description: "Store and read named values", configFields: ["name", "value"] },
      { type: "mathExpression", label: "Math Expression", description: "Compute arithmetic expressions", configFields: ["expression"] },
      { type: "log", label: "Log", description: "Debug log to execution console", configFields: ["message"] },
    ],
  },
];

// ---------------------------------------------------------------------------
// Lookup maps (built once at module load)
// ---------------------------------------------------------------------------

export const NODE_TYPE_TO_CATEGORY = new Map<string, NodeCategoryId>();
export const NODE_TYPE_TO_COLOR = new Map<string, string>();
export const NODE_TYPE_TO_LABEL = new Map<string, string>();
export const NODE_TYPE_TO_FIELDS = new Map<string, string[]>();
export const NODE_TYPE_TO_DEF = new Map<string, NodeDef>();

for (const cat of NODE_CATEGORIES) {
  for (const node of cat.nodes) {
    NODE_TYPE_TO_CATEGORY.set(node.type, cat.id);
    NODE_TYPE_TO_COLOR.set(node.type, cat.color);
    NODE_TYPE_TO_LABEL.set(node.type, node.label);
    NODE_TYPE_TO_FIELDS.set(node.type, node.configFields ?? []);
    NODE_TYPE_TO_DEF.set(node.type, node);
  }
}

// Nodes that use true/false output handles (conditional branching)
export const CONDITIONAL_NODE_TYPES = new Set([
  "positionCheck",
  "fundCheck",
  "timeWindow",
  "timeCondition",
  "priceCondition",
  "andGate",
  "orGate",
  "notGate",
  "ifElse",
]);

// Nodes that are start-only (no input handle)
export const START_NODE_TYPES = new Set([
  "start",
  "webhookTrigger",
  "httpRequest",
  "priceAlert",
  "subscribeLtp",
  "subscribeQuote",
  "subscribeDepth",
]);

export function getTotalNodeCount(): number {
  return NODE_CATEGORIES.reduce((sum, cat) => sum + cat.nodes.length, 0);
}
