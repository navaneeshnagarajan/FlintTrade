/**
 * FlowTemplates — template definitions and workflow factories for FlowBuilderTool.
 */

import type { SavedWorkflow } from "@/stores/flowStore";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type Difficulty = "Beginner" | "Intermediate" | "Advanced";

export interface FlowTemplate {
  id: string;
  name: string;
  description: string;
  category: string;
  nodeCount: number;
  tags: string[];
  difficulty: Difficulty;
  workflow: Pick<SavedWorkflow, "nodes" | "edges">;
}

// ---------------------------------------------------------------------------
// Workflow factories
// ---------------------------------------------------------------------------

function makeSimpleMarketOrderWorkflow(): Pick<SavedWorkflow, "nodes" | "edges"> {
  return {
    nodes: [
      { id: "n1", type: "flowNode", position: { x: 120, y: 40 }, data: { label: "Start", nodeType: "start", category: "triggers", color: "#f59e0b", config: {} } },
      { id: "n2", type: "flowNode", position: { x: 120, y: 160 }, data: { label: "Time Window", nodeType: "timeWindow", category: "conditions", color: "#818cf8", config: { start: "09:15", end: "15:15" } } },
      { id: "n3", type: "flowNode", position: { x: 120, y: 300 }, data: { label: "Place Order", nodeType: "placeOrder", category: "actions", color: "#22c55e", config: { symbol: "NIFTY", exchange: "NSE_INDEX", qty: "1", product: "MIS", side: "BUY", type: "MARKET" } } },
    ],
    edges: [
      { id: "e1", source: "n1", target: "n2", animated: true },
      { id: "e2", source: "n2", target: "n3", animated: true },
    ],
  };
}

function makePriceAlertWorkflow(): Pick<SavedWorkflow, "nodes" | "edges"> {
  return {
    nodes: [
      { id: "n1", type: "flowNode", position: { x: 80, y: 40 }, data: { label: "Subscribe LTP", nodeType: "subscribeLtp", category: "websocket", color: "#34d399", config: { symbol: "NIFTY", exchange: "NSE_INDEX" } } },
      { id: "n2", type: "flowNode", position: { x: 80, y: 160 }, data: { label: "Price Condition", nodeType: "priceCondition", category: "conditions", color: "#818cf8", config: { operator: ">", threshold: "22000" } } },
      { id: "n3", type: "flowNode", position: { x: 20, y: 300 }, data: { label: "Place Order", nodeType: "placeOrder", category: "actions", color: "#22c55e", config: { symbol: "NIFTY25JUNCE", exchange: "NFO", qty: "25", product: "MIS", side: "BUY", type: "MARKET" } } },
      { id: "n4", type: "flowNode", position: { x: 220, y: 300 }, data: { label: "Telegram Alert", nodeType: "telegramAlert", category: "utilities", color: "#a78bfa", config: { message: "Price alert triggered" } } },
    ],
    edges: [
      { id: "e1", source: "n1", target: "n2", animated: true },
      { id: "e2", source: "n2", sourceHandle: "true", target: "n3", animated: true },
      { id: "e3", source: "n2", sourceHandle: "false", target: "n4", animated: true },
    ],
  };
}

function makeIntradayWorkflow(): Pick<SavedWorkflow, "nodes" | "edges"> {
  return {
    nodes: [
      { id: "n1", type: "flowNode", position: { x: 140, y: 30 }, data: { label: "Start", nodeType: "start", category: "triggers", color: "#f59e0b", config: {} } },
      { id: "n2", type: "flowNode", position: { x: 140, y: 140 }, data: { label: "Market Open", nodeType: "timeWindow", category: "conditions", color: "#818cf8", config: { start: "09:15", end: "09:30" } } },
      { id: "n3", type: "flowNode", position: { x: 140, y: 260 }, data: { label: "Fund Check", nodeType: "fundCheck", category: "conditions", color: "#818cf8", config: { minFunds: "50000" } } },
      { id: "n4", type: "flowNode", position: { x: 40, y: 390 }, data: { label: "Smart Order", nodeType: "smartOrder", category: "actions", color: "#22c55e", config: { symbol: "NIFTY", exchange: "NSE_INDEX", qty: "50", product: "MIS", side: "BUY", type: "MARKET" } } },
      { id: "n5", type: "flowNode", position: { x: 270, y: 390 }, data: { label: "3:15 PM Exit", nodeType: "timeCondition", category: "conditions", color: "#818cf8", config: { time: "15:15" } } },
      { id: "n6", type: "flowNode", position: { x: 270, y: 510 }, data: { label: "Close Positions", nodeType: "closePositions", category: "actions", color: "#22c55e", config: {} } },
    ],
    edges: [
      { id: "e1", source: "n1", target: "n2", animated: true },
      { id: "e2", source: "n2", target: "n3", animated: true },
      { id: "e3", source: "n3", sourceHandle: "true", target: "n4", animated: true },
      { id: "e4", source: "n3", sourceHandle: "false", target: "n5", animated: true },
      { id: "e5", source: "n5", target: "n6", animated: true },
    ],
  };
}

// ---------------------------------------------------------------------------
// Template registry
// ---------------------------------------------------------------------------

export const FLOW_TEMPLATES: FlowTemplate[] = [
  {
    id: "simple_market_order",
    name: "Simple Market Order",
    description: "Draft sequence: Start trigger → Time window gate → Place Order node.",
    category: "Basic",
    nodeCount: 3,
    tags: ["Start", "Time Window", "Place Order"],
    difficulty: "Beginner",
    workflow: makeSimpleMarketOrderWorkflow(),
  },
  {
    id: "price_alert_order",
    name: "Price Alert → Order",
    description: "Draft sequence: LTP source → Price condition → Order and Telegram branches.",
    category: "Triggers",
    nodeCount: 4,
    tags: ["LTP", "Price Condition", "Options Order"],
    difficulty: "Beginner",
    workflow: makePriceAlertWorkflow(),
  },
  {
    id: "intraday_time_strategy",
    name: "Intraday Time Strategy",
    description: "Draft sequence: Market window → Fund check → Smart Order node → 3:15 PM exit branch.",
    category: "Intraday",
    nodeCount: 6,
    tags: ["Time Window", "Fund Check", "Smart Order", "Close Positions"],
    difficulty: "Intermediate",
    workflow: makeIntradayWorkflow(),
  },
  {
    id: "ema_crossover_auto",
    name: "EMA Crossover Auto Trader",
    description: "Planned draft for an LTP source, EMA crossover, time gate, Smart Order node, and Telegram branch.",
    category: "Trend Following",
    nodeCount: 8,
    tags: ["EMA", "Smart Order", "Telegram"],
    difficulty: "Beginner",
    workflow: { nodes: [], edges: [] },
  },
  {
    id: "webhook_order_handler",
    name: "Webhook Order Handler",
    description: "Planned draft for a signed generic webhook relay, action parsing, position check, and Place Order node.",
    category: "Automation",
    nodeCount: 6,
    tags: ["Webhook", "Place Order"],
    difficulty: "Beginner",
    workflow: { nodes: [], edges: [] },
  },
  {
    id: "morning_square_off",
    name: "Morning Square-Off Guard",
    description: "Planned draft for a 9:16 AM position check, Close Positions node, and Telegram summary.",
    category: "Risk Management",
    nodeCount: 7,
    tags: ["Close Positions", "Telegram", "Scheduled"],
    difficulty: "Intermediate",
    workflow: { nodes: [], edges: [] },
  },
  {
    id: "options_expiry_exit",
    name: "Options Expiry Day Exit",
    description: "Planned draft for an expiry-day option-chain check with cancel and close nodes.",
    category: "Options",
    nodeCount: 14,
    tags: ["Expiry", "Option Chain", "Risk"],
    difficulty: "Advanced",
    workflow: { nodes: [], edges: [] },
  },
  {
    id: "grid_rebalancer",
    name: "Grid Rebalancer",
    description: "Planned draft for an LTP-centred grid, depth source, and breakout repricing branch.",
    category: "Algorithmic",
    nodeCount: 18,
    tags: ["Grid", "Depth", "Variable", "Smart Order"],
    difficulty: "Advanced",
    workflow: { nodes: [], edges: [] },
  },
];
