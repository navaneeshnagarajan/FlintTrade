/**
 * nodeRegistry.ts — Node category definitions, metadata descriptors, and lookup maps.
 *
 * Single source of truth for all 54 flow builder nodes.
 * Absorbed from openalgo-flow node registry.
 *
 * Pattern: metadata-driven node rendering (inspired by n8n).
 * Every node type carries full field descriptors so ConfigPanel can render
 * forms declaratively without hardcoded field maps.
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

/** Validation constraints for a config field. */
export interface NodeFieldValidation {
  min?: number;
  max?: number;
  /** RegExp source string (no delimiters). */
  pattern?: string;
}

/**
 * Descriptor for a single configurable field on a node.
 * Used by ConfigPanel to render the appropriate input widget.
 */
export interface NodeFieldDescriptor {
  key: string;
  label: string;
  /**
   * - string      → plain text Input
   * - number      → numeric Input (min/max from validation)
   * - boolean     → Switch
   * - select      → Select with options[]
   * - expression  → textarea with {{variable}} interpolation
   * - symbol      → symbol search autocomplete
   * - exchange    → exchange selector dropdown
   */
  type: "string" | "number" | "boolean" | "select" | "expression" | "symbol" | "exchange";
  required?: boolean;
  default?: unknown;
  placeholder?: string;
  /** Only meaningful when type === "select". */
  options?: { label: string; value: string }[];
  validation?: NodeFieldValidation;
  helpText?: string;
}

/** Full metadata for a node type, used by the palette and config panel. */
export interface NodeTypeDescriptor {
  type: string;
  label: string;
  category: NodeCategoryId;
  description: string;
  /** lucide-react icon name (PascalCase). */
  icon: string;
  color: string;
  inputs: { id: string; label: string; type: "default" | "conditional" }[];
  outputs: { id: string; label: string; type: "default" | "true" | "false" }[];
  fields: NodeFieldDescriptor[];
}

/**
 * Legacy slim definition — kept for nodes that do not yet have full descriptors.
 * Fields that are present in NodeTypeDescriptor are reused; everything else
 * defaults to an empty array / sensible fallback.
 */
export interface NodeDef {
  type: string;
  label: string;
  description: string;
  /** Ordered list of field keys — derived from NodeTypeDescriptor.fields when available. */
  configFields?: string[];
  descriptor?: NodeTypeDescriptor;
}

export interface NodeCategoryDef {
  id: NodeCategoryId;
  label: string;
  color: string;
  nodes: NodeDef[];
}

// ---------------------------------------------------------------------------
// Category colour map (design tokens)
// ---------------------------------------------------------------------------

export const CATEGORY_COLORS: Record<NodeCategoryId, string> = {
  triggers:   "#f59e0b",   // amber
  actions:    "#22c55e",   // green (orders)
  conditions: "#818cf8",   // indigo
  logic:      "#ec4899",   // pink
  data:       "#38bdf8",   // sky blue
  websocket:  "#34d399",   // teal/emerald
  risk:       "#f97316",   // orange
  utilities:  "#a78bfa",   // violet
};

// ---------------------------------------------------------------------------
// Shared field fragments (reused across multiple node types)
// ---------------------------------------------------------------------------

const SYMBOL_FIELD: NodeFieldDescriptor = {
  key: "symbol",
  label: "Symbol",
  type: "symbol",
  required: true,
  placeholder: "e.g. NIFTY",
  helpText: "Instrument symbol as recognised by OpenAlgo",
};

const EXCHANGE_FIELD: NodeFieldDescriptor = {
  key: "exchange",
  label: "Exchange",
  type: "exchange",
  required: true,
  default: "NSE",
  helpText: "Exchange segment",
};

const QTY_FIELD: NodeFieldDescriptor = {
  key: "qty",
  label: "Quantity",
  type: "number",
  required: true,
  default: 1,
  placeholder: "e.g. 50",
  validation: { min: 1 },
  helpText: "Number of units / lots",
};

const PRODUCT_FIELD: NodeFieldDescriptor = {
  key: "product",
  label: "Product",
  type: "select",
  required: true,
  default: "MIS",
  options: [
    { label: "MIS (Intraday)", value: "MIS" },
    { label: "CNC (Delivery)", value: "CNC" },
    { label: "NRML (Carry Forward)", value: "NRML" },
  ],
};

const PRICETYPE_FIELD: NodeFieldDescriptor = {
  key: "pricetype",
  label: "Price Type",
  type: "select",
  required: true,
  default: "MARKET",
  options: [
    { label: "MARKET", value: "MARKET" },
    { label: "LIMIT", value: "LIMIT" },
    { label: "SL", value: "SL" },
    { label: "SL-M", value: "SL-M" },
  ],
};

// ---------------------------------------------------------------------------
// Full NodeTypeDescriptor definitions for key nodes
// ---------------------------------------------------------------------------

const DESCRIPTOR_PLACE_ORDER: NodeTypeDescriptor = {
  type: "placeOrder",
  label: "Place Order",
  category: "actions",
  description: "Market / limit / SL order via OpenAlgo",
  icon: "ShoppingCart",
  color: CATEGORY_COLORS.actions,
  inputs: [{ id: "in", label: "In", type: "default" }],
  outputs: [{ id: "out", label: "Out", type: "default" }],
  fields: [
    SYMBOL_FIELD,
    EXCHANGE_FIELD,
    {
      key: "action",
      label: "Action",
      type: "select",
      required: true,
      default: "BUY",
      options: [
        { label: "BUY", value: "BUY" },
        { label: "SELL", value: "SELL" },
      ],
    },
    QTY_FIELD,
    PRODUCT_FIELD,
    PRICETYPE_FIELD,
    {
      key: "price",
      label: "Price",
      type: "number",
      placeholder: "0 for MARKET",
      default: 0,
      validation: { min: 0 },
      helpText: "Limit/SL price. Use 0 for MARKET orders.",
    },
  ],
};

const DESCRIPTOR_PRICE_CONDITION: NodeTypeDescriptor = {
  type: "priceCondition",
  label: "Price Condition",
  category: "conditions",
  description: "If price > / < / = threshold",
  icon: "TrendingUp",
  color: CATEGORY_COLORS.conditions,
  inputs: [{ id: "in", label: "In", type: "default" }],
  outputs: [
    { id: "true", label: "True", type: "true" },
    { id: "false", label: "False", type: "false" },
  ],
  fields: [
    SYMBOL_FIELD,
    EXCHANGE_FIELD,
    {
      key: "operator",
      label: "Operator",
      type: "select",
      required: true,
      default: "above",
      options: [
        { label: "Above", value: "above" },
        { label: "Below", value: "below" },
        { label: "Crosses Above", value: "crossesAbove" },
        { label: "Crosses Below", value: "crossesBelow" },
        { label: "Equals", value: "equals" },
      ],
    },
    {
      key: "value",
      label: "Threshold Value",
      type: "number",
      required: true,
      placeholder: "e.g. 22000",
      validation: { min: 0 },
      helpText: "Price level to compare against",
    },
  ],
};

const DESCRIPTOR_TIME_CONDITION: NodeTypeDescriptor = {
  type: "timeCondition",
  label: "Time Condition",
  category: "conditions",
  description: "Specific time-based gate",
  icon: "Clock",
  color: CATEGORY_COLORS.conditions,
  inputs: [{ id: "in", label: "In", type: "default" }],
  outputs: [
    { id: "true", label: "True", type: "true" },
    { id: "false", label: "False", type: "false" },
  ],
  fields: [
    {
      key: "time",
      label: "Time (HH:MM)",
      type: "string",
      required: true,
      placeholder: "09:15",
      validation: { pattern: "^([01]\\d|2[0-3]):[0-5]\\d$" },
      helpText: "24-hour time in IST (Asia/Kolkata)",
    },
    {
      key: "timezone",
      label: "Timezone",
      type: "select",
      default: "Asia/Kolkata",
      options: [
        { label: "IST (Asia/Kolkata)", value: "Asia/Kolkata" },
        { label: "UTC", value: "UTC" },
      ],
    },
  ],
};

const DESCRIPTOR_TELEGRAM_ALERT: NodeTypeDescriptor = {
  type: "telegramAlert",
  label: "Telegram Alert",
  category: "utilities",
  description: "Send signal to Telegram bot",
  icon: "Send",
  color: CATEGORY_COLORS.utilities,
  inputs: [{ id: "in", label: "In", type: "default" }],
  outputs: [{ id: "out", label: "Out", type: "default" }],
  fields: [
    {
      key: "message",
      label: "Message",
      type: "expression",
      required: true,
      placeholder: "Order placed: {{upstream.placeOrder.symbol}} @ {{upstream.placeOrder.price}}",
      helpText: "Use {{variable}} syntax to interpolate upstream outputs or built-ins like {{$now}}.",
    },
  ],
};

const DESCRIPTOR_DELAY: NodeTypeDescriptor = {
  type: "delay",
  label: "Delay",
  category: "utilities",
  description: "Wait N seconds before next node",
  icon: "Timer",
  color: CATEGORY_COLORS.utilities,
  inputs: [{ id: "in", label: "In", type: "default" }],
  outputs: [{ id: "out", label: "Out", type: "default" }],
  fields: [
    {
      key: "seconds",
      label: "Seconds",
      type: "number",
      required: true,
      default: 5,
      placeholder: "5",
      validation: { min: 1, max: 3600 },
      helpText: "How many seconds to pause execution (1–3600)",
    },
  ],
};

const DESCRIPTOR_IF_ELSE: NodeTypeDescriptor = {
  type: "ifElse",
  label: "If / Else",
  category: "logic",
  description: "Two-branch conditional",
  icon: "GitBranch",
  color: CATEGORY_COLORS.logic,
  inputs: [{ id: "in", label: "In", type: "default" }],
  outputs: [
    { id: "true", label: "True", type: "true" },
    { id: "false", label: "False", type: "false" },
  ],
  fields: [
    {
      key: "condition",
      label: "Condition",
      type: "expression",
      required: true,
      placeholder: "{{upstream.priceCondition.result}} == true",
      helpText: "Expression that evaluates to true or false. Supports {{variable}} syntax.",
    },
  ],
};

// ---------------------------------------------------------------------------
// Price Alert trigger — 10 condition types
// ---------------------------------------------------------------------------

export type PriceAlertCondition =
  | "crossingUp"
  | "crossingDown"
  | "enteringChannel"
  | "exitingChannel"
  | "movingUpPct"
  | "movingDownPct"
  | "greaterThan"
  | "lessThan"
  | "insideChannel"
  | "outsideChannel";

export const PRICE_ALERT_CONDITIONS: { label: string; value: PriceAlertCondition }[] = [
  { label: "Crossing Up",       value: "crossingUp" },
  { label: "Crossing Down",     value: "crossingDown" },
  { label: "Entering Channel",  value: "enteringChannel" },
  { label: "Exiting Channel",   value: "exitingChannel" },
  { label: "Moving Up %",       value: "movingUpPct" },
  { label: "Moving Down %",     value: "movingDownPct" },
  { label: "Greater Than",      value: "greaterThan" },
  { label: "Less Than",         value: "lessThan" },
  { label: "Inside Channel",    value: "insideChannel" },
  { label: "Outside Channel",   value: "outsideChannel" },
];

/** Conditions that require two price inputs (upper + lower bound). */
export const CHANNEL_CONDITIONS = new Set<PriceAlertCondition>([
  "enteringChannel",
  "exitingChannel",
  "insideChannel",
  "outsideChannel",
]);

/** Conditions that require a percentage value rather than an absolute price. */
export const PERCENT_CONDITIONS = new Set<PriceAlertCondition>([
  "movingUpPct",
  "movingDownPct",
]);

const DESCRIPTOR_PRICE_ALERT: NodeTypeDescriptor = {
  type: "priceAlert",
  label: "Price Alert",
  category: "triggers",
  description: "Trigger when a price condition is met (10 condition types)",
  icon: "BellRing",
  color: CATEGORY_COLORS.triggers,
  inputs: [],
  outputs: [{ id: "out", label: "Triggered", type: "default" }],
  fields: [
    SYMBOL_FIELD,
    EXCHANGE_FIELD,
    {
      key: "condition",
      label: "Condition",
      type: "select",
      required: true,
      default: "crossingUp",
      options: PRICE_ALERT_CONDITIONS,
      helpText: "The type of price condition to monitor",
    },
    {
      key: "price",
      label: "Price / Lower Bound",
      type: "number",
      required: true,
      placeholder: "e.g. 22000",
      validation: { min: 0 },
      helpText: "Target price. For channel conditions, this is the lower bound.",
    },
    {
      key: "priceUpper",
      label: "Upper Bound",
      type: "number",
      placeholder: "e.g. 22500",
      validation: { min: 0 },
      helpText: "Upper bound for channel conditions (Entering/Exiting/Inside/Outside Channel)",
    },
    {
      key: "pctValue",
      label: "Percentage (%)",
      type: "number",
      placeholder: "e.g. 2.5",
      validation: { min: 0.01, max: 100 },
      helpText: "Percentage move threshold for Moving Up % / Moving Down % conditions",
    },
    {
      key: "cooldownSecs",
      label: "Cooldown (seconds)",
      type: "number",
      default: 60,
      placeholder: "60",
      validation: { min: 0, max: 86400 },
      helpText: "Minimum time between repeated triggers (0 = trigger every tick)",
    },
  ],
};

/** Map from node type string to its full NodeTypeDescriptor (only for nodes with one). */
export const NODE_DESCRIPTORS = new Map<string, NodeTypeDescriptor>([
  ["placeOrder",      DESCRIPTOR_PLACE_ORDER],
  ["priceCondition",  DESCRIPTOR_PRICE_CONDITION],
  ["timeCondition",   DESCRIPTOR_TIME_CONDITION],
  ["telegramAlert",   DESCRIPTOR_TELEGRAM_ALERT],
  ["delay",           DESCRIPTOR_DELAY],
  ["ifElse",          DESCRIPTOR_IF_ELSE],
  ["priceAlert",      DESCRIPTOR_PRICE_ALERT],
]);

// ---------------------------------------------------------------------------
// Helper: build a legacy NodeDef from a NodeTypeDescriptor
// ---------------------------------------------------------------------------

function descriptorToNodeDef(d: NodeTypeDescriptor): NodeDef {
  return {
    type: d.type,
    label: d.label,
    description: d.description,
    configFields: d.fields.map((f) => f.key),
    descriptor: d,
  };
}

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
      descriptorToNodeDef(DESCRIPTOR_PRICE_ALERT),
      { type: "webhookTrigger", label: "Webhook Trigger", description: "TradingView / Chartink webhook", configFields: ["path"] },
      { type: "httpRequest", label: "HTTP Request", description: "External HTTP event trigger", configFields: ["url", "method"] },
    ],
  },
  {
    id: "actions",
    label: "Orders",
    color: CATEGORY_COLORS.actions,
    nodes: [
      descriptorToNodeDef(DESCRIPTOR_PLACE_ORDER),
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
      descriptorToNodeDef(DESCRIPTOR_TIME_CONDITION),
      descriptorToNodeDef(DESCRIPTOR_PRICE_CONDITION),
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
      descriptorToNodeDef(DESCRIPTOR_IF_ELSE),
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
      descriptorToNodeDef(DESCRIPTOR_TELEGRAM_ALERT),
      { type: "webhookAlert", label: "Webhook (Outgoing)", description: "POST JSON payload to any URL", configFields: ["url"] },
      { type: "emailAlert", label: "Email Alert", description: "Send email notification", configFields: ["to", "subject"] },
      descriptorToNodeDef(DESCRIPTOR_DELAY),
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
