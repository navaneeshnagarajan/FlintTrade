/**
 * FlowBuilderTool — Visual workflow automation builder
 * Absorbed from:
 *   - openalgo-flow/frontend: 54-node complete flow builder
 *     Node categories: Triggers, Actions, Conditions, Logic Gates,
 *     Data, WebSocket, Risk, Utilities (all 54 nodes mapped below)
 *   - openalgo-flow/frontend/src/pages/Dashboard.tsx:
 *     Workflow card pattern, empty state, status icons
 *   - openalgo-flow/frontend/src/components/nodes/BaseNode.tsx:
 *     Node structure, handle pattern, category color system
 *   - openalgo-flow/frontend/src/pages/Editor.tsx:
 *     Canvas pattern, node palette sidebar, config panel, drag-drop
 *
 * Canvas built using pure React + SVG/CSS — no @xyflow/react dependency.
 */

import {
  useState,
  useRef,
  useEffect,
  type MouseEvent,
  type DragEvent,
  type ReactNode,
} from "react";
import {
  X,
  Workflow,
  Plus,
  Play,
  Pause,
  CheckCircle2,
  XCircle,
  AlertCircle,
  Zap,
  Filter,
  GitBranch,
  Database,
  Radio,
  Shield,
  Wrench,
  ChevronRight,
  Package,
  Save,
  Trash2,
  ChevronDown,
  ChevronUp,
  Terminal,
  FolderOpen,
  Info,
  RotateCcw,
} from "lucide-react";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type FlowStatus = "active" | "inactive" | "running" | "error";

type NodeCategoryId =
  | "triggers"
  | "actions"
  | "conditions"
  | "logic"
  | "data"
  | "websocket"
  | "risk"
  | "utilities";

interface NodeDef {
  type: string;
  label: string;
  description: string;
}

interface NodeCategoryDef {
  id: NodeCategoryId;
  label: string;
  icon: ReactNode;
  color: string;
  nodes: NodeDef[];
}

interface CanvasNode {
  id: string;
  type: string;
  label: string;
  category: NodeCategoryId;
  color: string;
  x: number;
  y: number;
  config: Record<string, string>;
}

interface CanvasEdge {
  id: string;
  sourceId: string;
  targetId: string;
  sourcePort: "output" | "true" | "false";
  targetPort: "input";
}

interface FlowWorkflow {
  id: string;
  name: string;
  nodes: CanvasNode[];
  edges: CanvasEdge[];
  updatedAt: string;
}

interface SavedFlow {
  id: string;
  name: string;
  description: string;
  nodeCount: number;
  edgeCount: number;
  status: FlowStatus;
  updatedAt: string;
  lastRun: string | null;
}

interface FlowTemplate {
  id: string;
  name: string;
  description: string;
  category: string;
  nodeCount: number;
  tags: string[];
  difficulty: "Beginner" | "Intermediate" | "Advanced";
  workflow: Pick<FlowWorkflow, "nodes" | "edges">;
}

// Port descriptor used during connection drawing
interface DraftEdge {
  sourceId: string;
  sourcePort: "output" | "true" | "false";
  mouseX: number;
  mouseY: number;
}

// ---------------------------------------------------------------------------
// Static data — absorbed from openalgo-flow node registry (54 nodes)
// ---------------------------------------------------------------------------

// Absorbed directly from openalgo-flow/frontend/src/components/nodes/index.ts
const NODE_CATEGORIES: NodeCategoryDef[] = [
  {
    id: "triggers",
    label: "Triggers",
    icon: <Zap size={13} />,
    color: "#f59e0b",
    nodes: [
      { type: "start", label: "Start", description: "Manual or scheduled entry point" },
      { type: "priceAlert", label: "Price Alert", description: "Trigger on price threshold breach" },
      { type: "webhookTrigger", label: "Webhook Trigger", description: "TradingView / Chartink webhook" },
      { type: "httpRequest", label: "HTTP Request", description: "External HTTP event trigger" },
    ],
  },
  {
    id: "actions",
    label: "Actions",
    icon: <Play size={13} />,
    color: "#22c55e",
    nodes: [
      { type: "placeOrder", label: "Place Order", description: "Market / limit / SL order via OpenAlgo" },
      { type: "smartOrder", label: "Smart Order", description: "Position-aware order with quantity management" },
      { type: "optionsOrder", label: "Options Order", description: "Single options order" },
      { type: "optionsMultiOrder", label: "Options Multi Order", description: "Basket of options orders" },
      { type: "basketOrder", label: "Basket Order", description: "Multi-leg equity basket" },
      { type: "splitOrder", label: "Split Order", description: "Break large order into chunks" },
      { type: "cancelOrder", label: "Cancel Order", description: "Cancel a specific order" },
      { type: "cancelAllOrders", label: "Cancel All Orders", description: "Cancel all open orders" },
      { type: "modifyOrder", label: "Modify Order", description: "Change price, qty, or type" },
      { type: "closePositions", label: "Close Positions", description: "Square off all open positions" },
    ],
  },
  {
    id: "conditions",
    label: "Conditions",
    icon: <Filter size={13} />,
    color: "#818cf8",
    nodes: [
      { type: "positionCheck", label: "Position Check", description: "Branch on open position state" },
      { type: "fundCheck", label: "Fund Check", description: "Gate on available margin" },
      { type: "timeWindow", label: "Time Window", description: "Allow flow only within market hours" },
      { type: "timeCondition", label: "Time Condition", description: "Specific time-based gate" },
      { type: "priceCondition", label: "Price Condition", description: "If price > / < / = threshold" },
    ],
  },
  {
    id: "logic",
    label: "Logic Gates",
    icon: <GitBranch size={13} />,
    color: "#ec4899",
    nodes: [
      { type: "andGate", label: "AND Gate", description: "All inputs must be true" },
      { type: "orGate", label: "OR Gate", description: "Any input must be true" },
      { type: "notGate", label: "NOT Gate", description: "Invert boolean signal" },
    ],
  },
  {
    id: "data",
    label: "Data",
    icon: <Database size={13} />,
    color: "#38bdf8",
    nodes: [
      { type: "getQuote", label: "Get Quote", description: "LTP, bid/ask, OHLC" },
      { type: "getDepth", label: "Get Depth", description: "50-level order book" },
      { type: "getOrderStatus", label: "Order Status", description: "Check order fill state" },
      { type: "history", label: "History", description: "OHLCV historical bars" },
      { type: "openPosition", label: "Open Position", description: "Get current position details" },
      { type: "expiry", label: "Expiry", description: "Options expiry lookup" },
      { type: "intervals", label: "Intervals", description: "Available data intervals" },
      { type: "multiQuotes", label: "Multi Quotes", description: "Bulk quotes for multiple symbols" },
      { type: "symbol", label: "Symbol", description: "Resolve symbol across exchanges" },
      { type: "optionSymbol", label: "Option Symbol", description: "Options chain symbol resolver" },
      { type: "orderBook", label: "Order Book", description: "Get full order book" },
      { type: "tradeBook", label: "Trade Book", description: "Get executed trades" },
      { type: "positionBook", label: "Position Book", description: "All current positions" },
      { type: "syntheticFuture", label: "Synthetic Future", description: "Construct synthetic F&O" },
      { type: "optionChain", label: "Option Chain", description: "Full chain with Greeks" },
      { type: "holidays", label: "Holidays", description: "Market holiday calendar" },
      { type: "timings", label: "Timings", description: "Exchange trading hours" },
    ],
  },
  {
    id: "websocket",
    label: "WebSocket",
    icon: <Radio size={13} />,
    color: "#34d399",
    nodes: [
      { type: "subscribeLtp", label: "Subscribe LTP", description: "Real-time last traded price" },
      { type: "subscribeQuote", label: "Subscribe Quote", description: "Real-time quote stream" },
      { type: "subscribeDepth", label: "Subscribe Depth", description: "50-level depth stream" },
      { type: "unsubscribe", label: "Unsubscribe", description: "Stop streaming for symbol" },
    ],
  },
  {
    id: "risk",
    label: "Risk Management",
    icon: <Shield size={13} />,
    color: "#f97316",
    nodes: [
      { type: "holdings", label: "Holdings", description: "Delivery / long-term positions" },
      { type: "funds", label: "Funds", description: "Account balance and margins" },
      { type: "margin", label: "Margin", description: "Calculate required margin" },
    ],
  },
  {
    id: "utilities",
    label: "Utilities",
    icon: <Wrench size={13} />,
    color: "#a78bfa",
    nodes: [
      { type: "telegramAlert", label: "Telegram Alert", description: "Send signal to Telegram bot" },
      { type: "delay", label: "Delay", description: "Wait N seconds before next node" },
      { type: "waitUntil", label: "Wait Until", description: "Pause until condition is met" },
      { type: "group", label: "Group", description: "Bundle nodes into a sub-flow" },
      { type: "variable", label: "Variable", description: "Store and read named values" },
      { type: "mathExpression", label: "Math Expression", description: "Compute arithmetic expressions" },
      { type: "log", label: "Log", description: "Debug log to execution console" },
    ],
  },
];

// Look-up maps built once
const NODE_TYPE_TO_CATEGORY = new Map<string, NodeCategoryId>();
const NODE_TYPE_TO_COLOR = new Map<string, string>();
const NODE_TYPE_TO_LABEL = new Map<string, string>();
for (const cat of NODE_CATEGORIES) {
  for (const node of cat.nodes) {
    NODE_TYPE_TO_CATEGORY.set(node.type, cat.id);
    NODE_TYPE_TO_COLOR.set(node.type, cat.color);
    NODE_TYPE_TO_LABEL.set(node.type, node.label);
  }
}

// ---------------------------------------------------------------------------
// Template workflows — pre-wired nodes for "Simple Market Order", etc.
// ---------------------------------------------------------------------------

function makeSimpleMarketOrderWorkflow(): Pick<FlowWorkflow, "nodes" | "edges"> {
  return {
    nodes: [
      { id: "n1", type: "start", label: "Start", category: "triggers", color: "#f59e0b", x: 80, y: 60, config: {} },
      { id: "n2", type: "timeWindow", label: "Time Window", category: "conditions", color: "#818cf8", x: 80, y: 180, config: { start: "09:15", end: "15:15" } },
      { id: "n3", type: "placeOrder", label: "Place Order", category: "actions", color: "#22c55e", x: 80, y: 310, config: { symbol: "NIFTY", exchange: "NSE_INDEX", qty: "1", product: "MIS", side: "BUY", type: "MARKET" } },
    ],
    edges: [
      { id: "e1", sourceId: "n1", targetId: "n2", sourcePort: "output", targetPort: "input" },
      { id: "e2", sourceId: "n2", targetId: "n3", sourcePort: "output", targetPort: "input" },
    ],
  };
}

function makePriceAlertOrderWorkflow(): Pick<FlowWorkflow, "nodes" | "edges"> {
  return {
    nodes: [
      { id: "n1", type: "subscribeLtp", label: "Subscribe LTP", category: "websocket", color: "#34d399", x: 60, y: 50, config: { symbol: "NIFTY", exchange: "NSE_INDEX" } },
      { id: "n2", type: "priceCondition", label: "Price Condition", category: "conditions", color: "#818cf8", x: 60, y: 170, config: { operator: ">", threshold: "22000" } },
      { id: "n3", type: "placeOrder", label: "Place Order", category: "actions", color: "#22c55e", x: 20, y: 300, config: { symbol: "NIFTY25JUNCE", exchange: "NFO", qty: "25", product: "MIS", side: "BUY", type: "MARKET" } },
      { id: "n4", type: "telegramAlert", label: "Telegram Alert", category: "utilities", color: "#a78bfa", x: 200, y: 300, config: { message: "Price alert triggered" } },
    ],
    edges: [
      { id: "e1", sourceId: "n1", targetId: "n2", sourcePort: "output", targetPort: "input" },
      { id: "e2", sourceId: "n2", targetId: "n3", sourcePort: "true", targetPort: "input" },
      { id: "e3", sourceId: "n2", targetId: "n4", sourcePort: "false", targetPort: "input" },
    ],
  };
}

function makeIntradayTimeStrategyWorkflow(): Pick<FlowWorkflow, "nodes" | "edges"> {
  return {
    nodes: [
      { id: "n1", type: "start", label: "Start", category: "triggers", color: "#f59e0b", x: 100, y: 40, config: {} },
      { id: "n2", type: "timeWindow", label: "Market Open", category: "conditions", color: "#818cf8", x: 100, y: 150, config: { start: "09:15", end: "09:30" } },
      { id: "n3", type: "fundCheck", label: "Fund Check", category: "conditions", color: "#818cf8", x: 100, y: 260, config: { minFunds: "50000" } },
      { id: "n4", type: "smartOrder", label: "Smart Order", category: "actions", color: "#22c55e", x: 60, y: 380, config: { symbol: "NIFTY", exchange: "NSE_INDEX", qty: "50", product: "MIS", side: "BUY", type: "MARKET" } },
      { id: "n5", type: "timeCondition", label: "3:15 PM Exit", category: "conditions", color: "#818cf8", x: 260, y: 380, config: { time: "15:15" } },
      { id: "n6", type: "closePositions", label: "Close Positions", category: "actions", color: "#22c55e", x: 260, y: 490, config: {} },
    ],
    edges: [
      { id: "e1", sourceId: "n1", targetId: "n2", sourcePort: "output", targetPort: "input" },
      { id: "e2", sourceId: "n2", targetId: "n3", sourcePort: "output", targetPort: "input" },
      { id: "e3", sourceId: "n3", targetId: "n4", sourcePort: "true", targetPort: "input" },
      { id: "e4", sourceId: "n3", targetId: "n5", sourcePort: "false", targetPort: "input" },
      { id: "e5", sourceId: "n5", targetId: "n6", sourcePort: "output", targetPort: "input" },
    ],
  };
}

const FLOW_TEMPLATES: FlowTemplate[] = [
  {
    id: "simple_market_order",
    name: "Simple Market Order",
    description: "Start trigger → Time window gate → Place market order. The minimal viable flow for any timed execution.",
    category: "Basic",
    nodeCount: 3,
    tags: ["Start", "Time Window", "Place Order"],
    difficulty: "Beginner",
    workflow: makeSimpleMarketOrderWorkflow(),
  },
  {
    id: "price_alert_order",
    name: "Price Alert → Order",
    description: "Subscribe LTP stream → Price condition check → CE order on breach, Telegram alert on no-breach.",
    category: "Triggers",
    nodeCount: 4,
    tags: ["LTP", "Price Condition", "Options Order"],
    difficulty: "Beginner",
    workflow: makePriceAlertOrderWorkflow(),
  },
  {
    id: "intraday_time_strategy",
    name: "Intraday Time Strategy",
    description: "Start → Market open window → Fund check → Smart order entry → Scheduled 3:15 PM square-off.",
    category: "Intraday",
    nodeCount: 6,
    tags: ["Time Window", "Fund Check", "Smart Order", "Close Positions"],
    difficulty: "Intermediate",
    workflow: makeIntradayTimeStrategyWorkflow(),
  },
  {
    id: "ema_crossover_auto",
    name: "EMA Crossover Auto Trader",
    description: "Subscribe to LTP, compute EMA 9/21 crossover, place smart order on signal. Includes time window gate and Telegram alert.",
    category: "Trend Following",
    nodeCount: 8,
    tags: ["EMA", "Smart Order", "Telegram"],
    difficulty: "Beginner",
    workflow: { nodes: [], edges: [] },
  },
  {
    id: "tradingview_webhook",
    name: "TradingView Webhook Handler",
    description: "Receive TradingView Pine alerts via webhook, parse action (BUY/SELL), route to place order with position check.",
    category: "Automation",
    nodeCount: 6,
    tags: ["TradingView", "Webhook", "Place Order"],
    difficulty: "Beginner",
    workflow: { nodes: [], edges: [] },
  },
  {
    id: "morning_square_off",
    name: "Morning Square-Off Guard",
    description: "At 9:16 AM, check positions. If overnight F&O positions exist, close all before CNC cutoff. Sends Telegram summary.",
    category: "Risk Management",
    nodeCount: 7,
    tags: ["Close Positions", "Telegram", "Scheduled"],
    difficulty: "Intermediate",
    workflow: { nodes: [], edges: [] },
  },
  {
    id: "options_expiry_exit",
    name: "Options Expiry Day Exit",
    description: "On expiry day at 3:00 PM, fetch option chain, identify short positions near strike, cancel and close. Walk-away logic.",
    category: "Options",
    nodeCount: 14,
    tags: ["Expiry", "Option Chain", "Risk"],
    difficulty: "Advanced",
    workflow: { nodes: [], edges: [] },
  },
  {
    id: "grid_rebalancer",
    name: "Grid Rebalancer",
    description: "Deploy arithmetic grid around LTP. Subscribe depth for spread tracking. Auto-reprice grid on breakout. State via variable nodes.",
    category: "Algorithmic",
    nodeCount: 18,
    tags: ["Grid", "Depth", "Variable", "Smart Order"],
    difficulty: "Advanced",
    workflow: { nodes: [], edges: [] },
  },
];

// ---------------------------------------------------------------------------
// Canvas geometry constants
// ---------------------------------------------------------------------------

const NODE_W = 164;
const NODE_H = 72; // approximate, collapsed node
const PORT_R = 5;

// Compute port screen coordinates for a node
function outputPortPos(node: CanvasNode, port: "output" | "true" | "false") {
  if (port === "true") return { x: node.x + NODE_W * 0.3, y: node.y + NODE_H };
  if (port === "false") return { x: node.x + NODE_W * 0.7, y: node.y + NODE_H };
  return { x: node.x + NODE_W / 2, y: node.y + NODE_H };
}

function inputPortPos(node: CanvasNode) {
  return { x: node.x + NODE_W / 2, y: node.y };
}

// Smooth cubic bezier path between two points
function bezierPath(x1: number, y1: number, x2: number, y2: number) {
  const dy = Math.abs(y2 - y1) * 0.5;
  return `M ${x1} ${y1} C ${x1} ${y1 + dy}, ${x2} ${y2 - dy}, ${x2} ${y2}`;
}

function edgeColor(port: "output" | "true" | "false") {
  if (port === "true") return "#22c55e";
  if (port === "false") return "#f87171";
  return "#6c8ef0";
}

// Does a node type have conditional (true/false) outputs?
function hasConditionalOutputs(type: string) {
  const cond = ["positionCheck", "fundCheck", "timeWindow", "timeCondition", "priceCondition", "andGate", "orGate", "notGate"];
  return cond.includes(type);
}

function isStartNode(type: string) {
  return ["start", "webhookTrigger", "httpRequest", "priceAlert", "subscribeLtp", "subscribeQuote", "subscribeDepth"].includes(type);
}

// ---------------------------------------------------------------------------
// LocalStorage persistence
// ---------------------------------------------------------------------------

const LS_KEY = "flinttrade_flowbuilder_v1";

interface StoredData {
  flows: FlowWorkflow[];
}

function loadStored(): StoredData {
  try {
    const raw = localStorage.getItem(LS_KEY);
    if (raw) return JSON.parse(raw) as StoredData;
  } catch {
    // ignore
  }
  return { flows: [] };
}

function saveStored(data: StoredData) {
  try {
    localStorage.setItem(LS_KEY, JSON.stringify(data));
  } catch {
    // ignore
  }
}

// ---------------------------------------------------------------------------
// Sub-components — shared
// ---------------------------------------------------------------------------

function StatusIcon({ status }: { status: FlowStatus }) {
  switch (status) {
    case "active":
      return <CheckCircle2 size={12} className="text-emerald-400" />;
    case "running":
      return <Play size={12} className="text-primary animate-pulse" />;
    case "error":
      return <XCircle size={12} className="text-red-400" />;
    case "inactive":
    default:
      return <Pause size={12} className="text-text-muted" />;
  }
}

function DifficultyBadge({ level }: { level: FlowTemplate["difficulty"] }) {
  const map = {
    Beginner: "bg-bullish-bg text-emerald-400 border-bullish-border",
    Intermediate: "bg-surface-elevated text-primary border-border-default",
    Advanced: "bg-atm-bg text-amber-400 border-atm-border",
  };
  return (
    <Badge className={`text-xxs h-4 px-1.5 ${map[level]}`}>{level}</Badge>
  );
}

// ---------------------------------------------------------------------------
// Canvas Node component
// ---------------------------------------------------------------------------

interface CanvasNodeCardProps {
  node: CanvasNode;
  selected: boolean;
  onMouseDown: (e: MouseEvent<HTMLDivElement>, id: string) => void;
  onPortMouseDown: (e: MouseEvent<HTMLDivElement>, nodeId: string, port: "output" | "true" | "false") => void;
  onInputPortMouseUp: (e: MouseEvent<HTMLDivElement>, nodeId: string) => void;
}

function CanvasNodeCard({ node, selected, onMouseDown, onPortMouseDown, onInputPortMouseUp }: CanvasNodeCardProps) {
  const isConditional = hasConditionalOutputs(node.type);
  const isStart = isStartNode(node.type);

  return (
    <div
      style={{
        position: "absolute",
        left: node.x,
        top: node.y,
        width: NODE_W,
        userSelect: "none",
        cursor: "grab",
      }}
      onMouseDown={(e) => onMouseDown(e, node.id)}
    >
      {/* Input port — top center */}
      {!isStart && (
        <div
          style={{
            position: "absolute",
            top: -PORT_R,
            left: "50%",
            transform: "translateX(-50%)",
            width: PORT_R * 2,
            height: PORT_R * 2,
            borderRadius: "50%",
            background: "#6b6b8a",
            border: "2px solid #0a0a0f",
            zIndex: 10,
            cursor: "crosshair",
          }}
          onMouseUp={(e) => {
            e.stopPropagation();
            onInputPortMouseUp(e, node.id);
          }}
        />
      )}

      {/* Node card body */}
      <div
        style={{
          background: "#12121a",
          border: `1px solid ${selected ? node.color : "#1e1e2e"}`,
          borderLeft: `3px solid ${node.color}`,
          borderRadius: 6,
          boxShadow: selected ? `0 0 0 2px ${node.color}40` : "none",
          overflow: "hidden",
        }}
      >
        {/* Header */}
        <div style={{ padding: "6px 8px", display: "flex", alignItems: "center", gap: 6 }}>
          <div
            style={{
              width: 20,
              height: 20,
              borderRadius: 4,
              background: `${node.color}22`,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              color: node.color,
              flexShrink: 0,
            }}
          >
            <Zap size={10} />
          </div>
          <div style={{ minWidth: 0, flex: 1 }}>
            <div style={{ fontSize: 11, fontWeight: 600, color: "#e0e0f0", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
              {node.label}
            </div>
            <div style={{ fontSize: 9, color: "#6b6b8a", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
              {node.type}
            </div>
          </div>
        </div>

        {/* Config preview (up to 2 key-value pairs) */}
        {Object.keys(node.config).length > 0 && (
          <div style={{ padding: "0 8px 6px", display: "flex", flexDirection: "column", gap: 2 }}>
            {Object.entries(node.config).slice(0, 2).map(([k, v]) => (
              <div key={k} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", background: "#0a0a0f", borderRadius: 3, padding: "2px 5px" }}>
                <span style={{ fontSize: 9, color: "#6b6b8a" }}>{k}</span>
                <span style={{ fontSize: 9, color: "#c0c0d8", fontFamily: "monospace", maxWidth: 70, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{v}</span>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Output port(s) — bottom */}
      {isConditional ? (
        <>
          {/* True port */}
          <div
            title="True"
            style={{
              position: "absolute",
              bottom: -PORT_R,
              left: "30%",
              transform: "translateX(-50%)",
              width: PORT_R * 2,
              height: PORT_R * 2,
              borderRadius: "50%",
              background: "#22c55e",
              border: "2px solid #0a0a0f",
              zIndex: 10,
              cursor: "crosshair",
            }}
            onMouseDown={(e) => {
              e.stopPropagation();
              onPortMouseDown(e, node.id, "true");
            }}
          />
          {/* False port */}
          <div
            title="False"
            style={{
              position: "absolute",
              bottom: -PORT_R,
              left: "70%",
              transform: "translateX(-50%)",
              width: PORT_R * 2,
              height: PORT_R * 2,
              borderRadius: "50%",
              background: "#f87171",
              border: "2px solid #0a0a0f",
              zIndex: 10,
              cursor: "crosshair",
            }}
            onMouseDown={(e) => {
              e.stopPropagation();
              onPortMouseDown(e, node.id, "false");
            }}
          />
        </>
      ) : (
        <div
          title="Output"
          style={{
            position: "absolute",
            bottom: -PORT_R,
            left: "50%",
            transform: "translateX(-50%)",
            width: PORT_R * 2,
            height: PORT_R * 2,
            borderRadius: "50%",
            background: "#6c8ef0",
            border: "2px solid #0a0a0f",
            zIndex: 10,
            cursor: "crosshair",
          }}
          onMouseDown={(e) => {
            e.stopPropagation();
            onPortMouseDown(e, node.id, "output");
          }}
        />
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Config panel (right sidebar)
// ---------------------------------------------------------------------------

interface ConfigPanelProps {
  node: CanvasNode;
  onChange: (id: string, config: Record<string, string>) => void;
  onLabelChange: (id: string, label: string) => void;
  onDelete: (id: string) => void;
  onClose: () => void;
}

const CONFIG_FIELDS: Partial<Record<string, string[]>> = {
  placeOrder: ["symbol", "exchange", "qty", "product", "side", "type", "price"],
  smartOrder: ["symbol", "exchange", "qty", "product", "side", "type", "positionSize"],
  optionsOrder: ["symbol", "exchange", "qty", "product", "side", "type", "expiry", "strike", "optionType"],
  closePositions: [],
  cancelAllOrders: [],
  priceAlert: ["symbol", "exchange", "threshold", "operator"],
  priceCondition: ["operator", "threshold"],
  timeWindow: ["start", "end"],
  timeCondition: ["time"],
  fundCheck: ["minFunds"],
  positionCheck: ["symbol"],
  subscribeLtp: ["symbol", "exchange"],
  subscribeQuote: ["symbol", "exchange"],
  subscribeDepth: ["symbol", "exchange"],
  getQuote: ["symbol", "exchange"],
  telegramAlert: ["message"],
  delay: ["seconds"],
  variable: ["name", "value"],
  mathExpression: ["expression"],
  log: ["message"],
  webhookTrigger: ["path"],
  httpRequest: ["url", "method"],
};

function ConfigPanel({ node, onChange, onLabelChange, onDelete, onClose }: ConfigPanelProps) {
  const fields = CONFIG_FIELDS[node.type] ?? [];
  const [localConfig, setLocalConfig] = useState<Record<string, string>>(node.config);
  const [localLabel, setLocalLabel] = useState(node.label);

  useEffect(() => {
    setLocalConfig(node.config);
    setLocalLabel(node.label);
  }, [node.id, node.config, node.label]);

  function handleFieldChange(key: string, value: string) {
    const next = { ...localConfig, [key]: value };
    setLocalConfig(next);
    onChange(node.id, next);
  }

  function handleLabelBlur() {
    onLabelChange(node.id, localLabel);
  }

  return (
    <div
      style={{
        width: 220,
        flexShrink: 0,
        background: "#12121a",
        borderLeft: "1px solid #1e1e2e",
        display: "flex",
        flexDirection: "column",
        height: "100%",
        overflow: "hidden",
      }}
    >
      {/* Config header */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "8px 10px", borderBottom: "1px solid #1e1e2e" }}>
        <div>
          <div style={{ fontSize: 11, fontWeight: 600, color: "#e0e0f0" }}>Node Config</div>
          <div style={{ fontSize: 9, color: "#6b6b8a" }}>{node.type}</div>
        </div>
        <button onClick={onClose} style={{ color: "#6b6b8a", cursor: "pointer", background: "none", border: "none", padding: 2 }}>
          <X size={13} />
        </button>
      </div>

      <ScrollArea style={{ flex: 1 }}>
        <div style={{ padding: "10px" }}>
          {/* Label */}
          <div style={{ marginBottom: 10 }}>
            <Label style={{ fontSize: 10, color: "#9090b0", marginBottom: 4, display: "block" }}>Label</Label>
            <Input
              value={localLabel}
              onChange={(e) => setLocalLabel(e.target.value)}
              onBlur={handleLabelBlur}
              style={{ height: 28, fontSize: 11, background: "#0a0a0f", border: "1px solid #1e1e2e", color: "#e0e0f0" }}
            />
          </div>

          {/* Category badge */}
          <div style={{ marginBottom: 10 }}>
            <div style={{ fontSize: 9, display: "inline-flex", alignItems: "center", gap: 4, padding: "2px 6px", borderRadius: 4, background: `${node.color}22`, color: node.color, border: `1px solid ${node.color}44` }}>
              {node.category}
            </div>
          </div>

          {/* Dynamic fields */}
          {fields.length > 0 ? (
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              {fields.map((field) => (
                <div key={field}>
                  <Label style={{ fontSize: 10, color: "#9090b0", marginBottom: 3, display: "block", textTransform: "capitalize" }}>
                    {field.replace(/([A-Z])/g, " $1").toLowerCase()}
                  </Label>
                  <Input
                    value={localConfig[field] ?? ""}
                    onChange={(e) => handleFieldChange(field, e.target.value)}
                    placeholder={field}
                    style={{ height: 28, fontSize: 11, background: "#0a0a0f", border: "1px solid #1e1e2e", color: "#e0e0f0" }}
                  />
                </div>
              ))}
            </div>
          ) : (
            <div style={{ fontSize: 11, color: "#6b6b8a", padding: "8px 0" }}>
              No configuration fields for this node type.
            </div>
          )}

          {/* Delete */}
          <div style={{ marginTop: 16 }}>
            <Button
              size="sm"
              variant="ghost"
              className="w-full h-7 text-red-400 hover:text-red-300 hover:bg-red-950 text-xs gap-1.5 justify-start"
              onClick={() => onDelete(node.id)}
            >
              <Trash2 size={11} />
              Delete node
            </Button>
          </div>
        </div>
      </ScrollArea>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Node Palette sidebar
// ---------------------------------------------------------------------------

interface NodePaletteProps {
  onDragStart: (e: DragEvent<HTMLDivElement>, type: string) => void;
}

function NodePalette({ onDragStart }: NodePaletteProps) {
  const [expanded, setExpanded] = useState<Set<string>>(new Set(["triggers", "actions"]));
  const [search, setSearch] = useState("");

  function toggleCat(id: string) {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  const filtered = search.trim()
    ? NODE_CATEGORIES.map((cat) => ({
        ...cat,
        nodes: cat.nodes.filter((n) => n.label.toLowerCase().includes(search.toLowerCase()) || n.type.toLowerCase().includes(search.toLowerCase())),
      })).filter((cat) => cat.nodes.length > 0)
    : NODE_CATEGORIES;

  return (
    <div
      style={{
        width: 188,
        flexShrink: 0,
        background: "#0a0a0f",
        borderRight: "1px solid #1e1e2e",
        display: "flex",
        flexDirection: "column",
        height: "100%",
        overflow: "hidden",
      }}
    >
      <div style={{ padding: "8px", borderBottom: "1px solid #1e1e2e" }}>
        <div style={{ fontSize: 10, fontWeight: 600, color: "#9090b0", marginBottom: 5, textTransform: "uppercase", letterSpacing: "0.05em" }}>Node Palette</div>
        <input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search nodes..."
          style={{
            width: "100%",
            height: 26,
            fontSize: 11,
            background: "#12121a",
            border: "1px solid #1e1e2e",
            borderRadius: 4,
            color: "#e0e0f0",
            padding: "0 8px",
            outline: "none",
            boxSizing: "border-box",
          }}
        />
      </div>
      <div style={{ flex: 1, overflowY: "auto" }}>
        {filtered.map((cat) => (
          <div key={cat.id}>
            {/* Category header */}
            <button
              onClick={() => toggleCat(cat.id)}
              style={{
                width: "100%",
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                padding: "5px 8px",
                background: "#12121a",
                border: "none",
                borderBottom: "1px solid #1e1e2e",
                cursor: "pointer",
                color: cat.color,
              }}
            >
              <div style={{ display: "flex", alignItems: "center", gap: 5 }}>
                {cat.icon}
                <span style={{ fontSize: 10, fontWeight: 600 }}>{cat.label}</span>
                <span style={{ fontSize: 9, color: "#6b6b8a" }}>{cat.nodes.length}</span>
              </div>
              {expanded.has(cat.id) ? <ChevronUp size={10} /> : <ChevronDown size={10} />}
            </button>

            {/* Node items */}
            {expanded.has(cat.id) && (
              <div style={{ padding: "4px 6px", display: "flex", flexDirection: "column", gap: 2 }}>
                {cat.nodes.map((node) => (
                  <div
                    key={node.type}
                    draggable
                    onDragStart={(e) => onDragStart(e, node.type)}
                    title={node.description}
                    style={{
                      padding: "4px 6px",
                      borderRadius: 4,
                      background: "#12121a",
                      border: "1px solid #1e1e2e",
                      cursor: "grab",
                      display: "flex",
                      alignItems: "center",
                      gap: 5,
                    }}
                    onMouseEnter={(e) => { (e.currentTarget as HTMLDivElement).style.borderColor = cat.color; }}
                    onMouseLeave={(e) => { (e.currentTarget as HTMLDivElement).style.borderColor = "#1e1e2e"; }}
                  >
                    <div style={{ width: 6, height: 6, borderRadius: "50%", background: cat.color, flexShrink: 0 }} />
                    <span style={{ fontSize: 10, color: "#c0c0d8", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                      {node.label}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>
        ))}
      </div>

      {/* Drag hint */}
      <div style={{ padding: "6px 8px", borderTop: "1px solid #1e1e2e", fontSize: 9, color: "#404060", textAlign: "center" }}>
        Drag nodes onto the canvas
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Canvas (visual editor)
// ---------------------------------------------------------------------------

let nodeCounter = 1;
function genNodeId() { return `n${nodeCounter++}`; }
let edgeCounter = 1;
function genEdgeId() { return `e${edgeCounter++}`; }

interface CanvasProps {
  workflow: FlowWorkflow;
  onWorkflowChange: (w: FlowWorkflow) => void;
}

function Canvas({ workflow, onWorkflowChange }: CanvasProps) {
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [draftEdge, setDraftEdge] = useState<DraftEdge | null>(null);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [zoom, setZoom] = useState(1);

  const svgRef = useRef<SVGSVGElement>(null);
  const canvasRef = useRef<HTMLDivElement>(null);

  // Dragging node state
  const dragging = useRef<{ nodeId: string; startMouseX: number; startMouseY: number; startNodeX: number; startNodeY: number } | null>(null);
  // Panning state
  const panning = useRef<{ startMouseX: number; startMouseY: number; startPanX: number; startPanY: number } | null>(null);

  const { nodes, edges } = workflow;

  function update(next: Partial<FlowWorkflow>) {
    onWorkflowChange({ ...workflow, ...next, updatedAt: new Date().toISOString() });
  }

  // Convert screen coords to canvas coords
  function toCanvas(sx: number, sy: number) {
    const rect = canvasRef.current?.getBoundingClientRect() ?? { left: 0, top: 0 };
    return {
      x: (sx - rect.left - pan.x) / zoom,
      y: (sy - rect.top - pan.y) / zoom,
    };
  }

  // Node drag start
  function handleNodeMouseDown(e: MouseEvent<HTMLDivElement>, id: string) {
    if (e.button !== 0) return;
    e.stopPropagation();
    e.preventDefault();
    const node = nodes.find((n) => n.id === id);
    if (!node) return;
    setSelectedNodeId(id);
    dragging.current = { nodeId: id, startMouseX: e.clientX, startMouseY: e.clientY, startNodeX: node.x, startNodeY: node.y };
  }

  // Port drag start (begin drawing a connection)
  function handlePortMouseDown(e: MouseEvent<HTMLDivElement>, nodeId: string, port: "output" | "true" | "false") {
    e.stopPropagation();
    e.preventDefault();
    const canvas = toCanvas(e.clientX, e.clientY);
    setDraftEdge({ sourceId: nodeId, sourcePort: port, mouseX: canvas.x, mouseY: canvas.y });
  }

  // Port drop (complete connection)
  function handleInputPortMouseUp(_e: MouseEvent<HTMLDivElement>, targetId: string) {
    if (!draftEdge) return;
    if (draftEdge.sourceId === targetId) { setDraftEdge(null); return; }
    // Prevent duplicate edges
    const exists = edges.some((edge) => edge.sourceId === draftEdge.sourceId && edge.targetId === targetId && edge.sourcePort === draftEdge.sourcePort);
    if (!exists) {
      const newEdge: CanvasEdge = { id: genEdgeId(), sourceId: draftEdge.sourceId, targetId, sourcePort: draftEdge.sourcePort, targetPort: "input" };
      update({ edges: [...edges, newEdge] });
    }
    setDraftEdge(null);
  }

  // Canvas mouse move — drag node or draft edge
  function handleMouseMove(e: MouseEvent<HTMLDivElement>) {
    if (dragging.current) {
      const dx = (e.clientX - dragging.current.startMouseX) / zoom;
      const dy = (e.clientY - dragging.current.startMouseY) / zoom;
      const updatedNodes = nodes.map((n) =>
        n.id === dragging.current!.nodeId
          ? { ...n, x: Math.max(0, dragging.current!.startNodeX + dx), y: Math.max(0, dragging.current!.startNodeY + dy) }
          : n
      );
      update({ nodes: updatedNodes });
      return;
    }
    if (panning.current) {
      const dx = e.clientX - panning.current.startMouseX;
      const dy = e.clientY - panning.current.startMouseY;
      setPan({ x: panning.current.startPanX + dx, y: panning.current.startPanY + dy });
      return;
    }
    if (draftEdge) {
      const canvas = toCanvas(e.clientX, e.clientY);
      setDraftEdge((prev) => prev ? { ...prev, mouseX: canvas.x, mouseY: canvas.y } : null);
    }
  }

  function handleMouseUp() {
    dragging.current = null;
    panning.current = null;
    if (draftEdge) setDraftEdge(null);
  }

  // Click on blank canvas — deselect, start pan
  function handleCanvasMouseDown(e: MouseEvent<HTMLDivElement>) {
    if (e.button === 0) {
      setSelectedNodeId(null);
      panning.current = { startMouseX: e.clientX, startMouseY: e.clientY, startPanX: pan.x, startPanY: pan.y };
    }
  }

  // Scroll to zoom
  function handleWheel(e: React.WheelEvent<HTMLDivElement>) {
    e.preventDefault();
    const factor = e.deltaY < 0 ? 1.08 : 0.93;
    setZoom((z) => Math.max(0.25, Math.min(3, z * factor)));
  }

  // Drop from palette
  function handleDrop(e: DragEvent<HTMLDivElement>) {
    e.preventDefault();
    const type = e.dataTransfer.getData("application/flinttrade-node");
    if (!type) return;
    const canvas = toCanvas(e.clientX, e.clientY);
    const catId = NODE_TYPE_TO_CATEGORY.get(type) ?? "utilities";
    const color = NODE_TYPE_TO_COLOR.get(type) ?? "#a78bfa";
    const label = NODE_TYPE_TO_LABEL.get(type) ?? type;
    const newNode: CanvasNode = { id: genNodeId(), type, label, category: catId, color, x: canvas.x - NODE_W / 2, y: canvas.y - NODE_H / 2, config: {} };
    update({ nodes: [...nodes, newNode] });
  }

  function handleDragOver(e: DragEvent<HTMLDivElement>) { e.preventDefault(); e.dataTransfer.dropEffect = "copy"; }

  function handleNodeConfigChange(id: string, config: Record<string, string>) {
    update({ nodes: nodes.map((n) => n.id === id ? { ...n, config } : n) });
  }

  function handleNodeLabelChange(id: string, label: string) {
    update({ nodes: nodes.map((n) => n.id === id ? { ...n, label } : n) });
  }

  function handleNodeDelete(id: string) {
    update({ nodes: nodes.filter((n) => n.id !== id), edges: edges.filter((e) => e.sourceId !== id && e.targetId !== id) });
    setSelectedNodeId(null);
  }

  function handleEdgeDelete(edgeId: string) {
    update({ edges: edges.filter((e) => e.id !== edgeId) });
  }

  function resetView() { setPan({ x: 0, y: 0 }); setZoom(1); }

  const selectedNode = nodes.find((n) => n.id === selectedNodeId) ?? null;

  return (
    <div style={{ display: "flex", flex: 1, minWidth: 0, minHeight: 0, overflow: "hidden" }}>
      {/* Palette sidebar */}
      <NodePalette onDragStart={(e, type) => { e.dataTransfer.setData("application/flinttrade-node", type); e.dataTransfer.effectAllowed = "copy"; }} />

      {/* Canvas area */}
      <div
        ref={canvasRef}
        style={{ flex: 1, position: "relative", overflow: "hidden", background: "#0a0a0f", cursor: panning.current ? "grabbing" : "default" }}
        onMouseMove={handleMouseMove}
        onMouseUp={handleMouseUp}
        onMouseDown={handleCanvasMouseDown}
        onDragOver={handleDragOver}
        onDrop={handleDrop}
        onWheel={handleWheel}
      >
        {/* Grid background */}
        <svg style={{ position: "absolute", inset: 0, width: "100%", height: "100%", pointerEvents: "none" }}>
          <defs>
            <pattern id="grid" width={16 * zoom} height={16 * zoom} patternUnits="userSpaceOnUse" x={pan.x % (16 * zoom)} y={pan.y % (16 * zoom)}>
              <circle cx={0} cy={0} r={0.6} fill="#1e1e2e" />
            </pattern>
          </defs>
          <rect width="100%" height="100%" fill="url(#grid)" />
        </svg>

        {/* Transformed canvas content */}
        <div
          style={{
            position: "absolute",
            left: 0,
            top: 0,
            transform: `translate(${pan.x}px, ${pan.y}px) scale(${zoom})`,
            transformOrigin: "0 0",
            width: 2000,
            height: 2000,
          }}
        >
          {/* SVG layer for edges */}
          <svg
            ref={svgRef}
            style={{ position: "absolute", inset: 0, width: "100%", height: "100%", overflow: "visible", pointerEvents: "none" }}
          >
            {/* Existing edges */}
            {edges.map((edge) => {
              const src = nodes.find((n) => n.id === edge.sourceId);
              const tgt = nodes.find((n) => n.id === edge.targetId);
              if (!src || !tgt) return null;
              const sp = outputPortPos(src, edge.sourcePort);
              const tp = inputPortPos(tgt);
              const d = bezierPath(sp.x, sp.y, tp.x, tp.y);
              const color = edgeColor(edge.sourcePort);
              return (
                <g key={edge.id} style={{ pointerEvents: "all", cursor: "pointer" }} onClick={() => handleEdgeDelete(edge.id)}>
                  {/* Wider invisible hit target */}
                  <path d={d} fill="none" stroke="transparent" strokeWidth={12} />
                  <path d={d} fill="none" stroke={color} strokeWidth={1.5} strokeDasharray="5 3" opacity={0.7} />
                  {/* Midpoint delete indicator on hover */}
                  <title>Click to delete edge</title>
                </g>
              );
            })}

            {/* Draft (in-progress) edge */}
            {draftEdge && (() => {
              const src = nodes.find((n) => n.id === draftEdge.sourceId);
              if (!src) return null;
              const sp = outputPortPos(src, draftEdge.sourcePort);
              const d = bezierPath(sp.x, sp.y, draftEdge.mouseX, draftEdge.mouseY);
              const color = edgeColor(draftEdge.sourcePort);
              return (
                <path key="draft" d={d} fill="none" stroke={color} strokeWidth={1.5} strokeDasharray="4 3" opacity={0.5} />
              );
            })()}
          </svg>

          {/* Node cards */}
          {nodes.map((node) => (
            <CanvasNodeCard
              key={node.id}
              node={node}
              selected={node.id === selectedNodeId}
              onMouseDown={handleNodeMouseDown}
              onPortMouseDown={handlePortMouseDown}
              onInputPortMouseUp={handleInputPortMouseUp}
            />
          ))}
        </div>

        {/* Zoom controls */}
        <div style={{ position: "absolute", bottom: 12, left: 12, display: "flex", flexDirection: "column", gap: 4, zIndex: 20 }}>
          <button onClick={() => setZoom((z) => Math.min(3, z * 1.15))} style={zoomBtnStyle} title="Zoom in">+</button>
          <button onClick={resetView} style={{ ...zoomBtnStyle, fontSize: 9 }} title="Reset view"><RotateCcw size={10} /></button>
          <button onClick={() => setZoom((z) => Math.max(0.25, z * 0.87))} style={zoomBtnStyle} title="Zoom out">−</button>
        </div>

        {/* Zoom level indicator */}
        <div style={{ position: "absolute", bottom: 12, right: selectedNode ? 232 : 12, zIndex: 20, fontSize: 9, color: "#404060", background: "#12121a", border: "1px solid #1e1e2e", borderRadius: 4, padding: "2px 6px" }}>
          {Math.round(zoom * 100)}%
        </div>

        {/* Empty state */}
        {nodes.length === 0 && (
          <div style={{ position: "absolute", inset: 0, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", pointerEvents: "none" }}>
            <div style={{ textAlign: "center" }}>
              <div style={{ width: 48, height: 48, borderRadius: "50%", background: "#12121a", border: "1px solid #1e1e2e", display: "flex", alignItems: "center", justifyContent: "center", margin: "0 auto 12px" }}>
                <Workflow size={20} style={{ color: "#6b6b8a" }} />
              </div>
              <div style={{ fontSize: 13, color: "#e0e0f0", marginBottom: 4 }}>Empty canvas</div>
              <div style={{ fontSize: 11, color: "#6b6b8a" }}>Drag nodes from the palette to get started</div>
            </div>
          </div>
        )}
      </div>

      {/* Config panel (right) */}
      {selectedNode && (
        <ConfigPanel
          node={selectedNode}
          onChange={handleNodeConfigChange}
          onLabelChange={handleNodeLabelChange}
          onDelete={handleNodeDelete}
          onClose={() => setSelectedNodeId(null)}
        />
      )}
    </div>
  );
}

const zoomBtnStyle: React.CSSProperties = {
  width: 24,
  height: 24,
  background: "#12121a",
  border: "1px solid #1e1e2e",
  borderRadius: 4,
  color: "#9090b0",
  cursor: "pointer",
  fontSize: 14,
  display: "flex",
  alignItems: "center",
  justifyContent: "center",
  padding: 0,
};

// ---------------------------------------------------------------------------
// Canvas Editor (full screen editor for a workflow)
// ---------------------------------------------------------------------------

interface EditorViewProps {
  flow: FlowWorkflow;
  onSave: (w: FlowWorkflow) => void;
  onBack: () => void;
}

function EditorView({ flow, onSave, onBack }: EditorViewProps) {
  const [workflow, setWorkflow] = useState<FlowWorkflow>(flow);
  const [name, setName] = useState(flow.name);
  const [saved, setSaved] = useState(true);
  const [showRunNote, setShowRunNote] = useState(false);

  function handleWorkflowChange(w: FlowWorkflow) {
    setWorkflow(w);
    setSaved(false);
  }

  function handleSave() {
    const updated = { ...workflow, name };
    onSave(updated);
    setSaved(true);
  }

  function handleClearCanvas() {
    handleWorkflowChange({ ...workflow, nodes: [], edges: [] });
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", background: "#0a0a0f" }}>
      {/* Toolbar */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "6px 12px", borderBottom: "1px solid #1e1e2e", background: "#12121a", flexShrink: 0 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <button onClick={onBack} style={{ color: "#6b6b8a", background: "none", border: "none", cursor: "pointer", padding: 2, display: "flex", alignItems: "center" }}>
            <ChevronRight size={14} style={{ transform: "rotate(180deg)" }} />
          </button>
          <input
            value={name}
            onChange={(e) => { setName(e.target.value); setSaved(false); }}
            style={{ fontSize: 12, fontWeight: 600, background: "transparent", border: "1px solid transparent", borderRadius: 4, color: "#e0e0f0", padding: "2px 6px", outline: "none" }}
            onMouseEnter={(e) => { (e.currentTarget as HTMLInputElement).style.borderColor = "#1e1e2e"; }}
            onMouseLeave={(e) => { (e.currentTarget as HTMLInputElement).style.borderColor = "transparent"; }}
          />
          {!saved && <span style={{ fontSize: 10, color: "#6b6b8a" }}>Unsaved</span>}
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
          {/* Node/edge count */}
          <span style={{ fontSize: 10, color: "#6b6b8a" }}>{workflow.nodes.length} nodes · {workflow.edges.length} edges</span>

          <Button
            size="sm"
            variant="ghost"
            className="h-6 px-2 text-xs text-text-muted hover:text-text-primary gap-1"
            onClick={handleClearCanvas}
            title="Clear canvas"
          >
            <Trash2 size={11} />
          </Button>

          <Button
            size="sm"
            variant="ghost"
            className="h-6 px-2 text-xs text-amber-400 hover:text-amber-300 gap-1"
            onClick={() => setShowRunNote((v) => !v)}
          >
            <Terminal size={11} />
            Run
          </Button>

          <Button
            size="sm"
            className="h-6 px-3 bg-primary hover:bg-primary/90 text-white text-xs gap-1"
            onClick={handleSave}
            disabled={saved}
          >
            <Save size={11} />
            Save
          </Button>
        </div>
      </div>

      {/* Run backend note */}
      {showRunNote && (
        <div style={{ background: "#1a1a0a", borderBottom: "1px solid #2a2a1a", padding: "6px 12px", display: "flex", alignItems: "center", gap: 6 }}>
          <AlertCircle size={12} style={{ color: "#f59e0b", flexShrink: 0 }} />
          <span style={{ fontSize: 11, color: "#9090b0" }}>
            Connect the Python backend to execute flows. Run{" "}
            <span style={{ fontFamily: "monospace", color: "#e0e0f0" }}>python -m packages.automation.src.flow_runner</span>{" "}
            and enable execution in Settings.
          </span>
          <button onClick={() => setShowRunNote(false)} style={{ marginLeft: "auto", color: "#6b6b8a", background: "none", border: "none", cursor: "pointer" }}>
            <X size={11} />
          </button>
        </div>
      )}

      {/* Canvas + sidebars */}
      <div style={{ flex: 1, display: "flex", minHeight: 0 }}>
        <Canvas workflow={workflow} onWorkflowChange={handleWorkflowChange} />
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Flows Tab (list of saved flows)
// ---------------------------------------------------------------------------

interface FlowsTabProps {
  flows: FlowWorkflow[];
  onNew: () => void;
  onOpen: (id: string) => void;
  onDelete: (id: string) => void;
  onFromTemplate: () => void;
}

function FlowsTab({ flows, onNew, onOpen, onDelete, onFromTemplate }: FlowsTabProps) {
  const saved: SavedFlow[] = flows.map((f) => ({
    id: f.id,
    name: f.name,
    description: `${f.nodes.length} nodes, ${f.edges.length} edges`,
    nodeCount: f.nodes.length,
    edgeCount: f.edges.length,
    status: "inactive" as FlowStatus,
    updatedAt: f.updatedAt ? new Date(f.updatedAt).toLocaleDateString("en-IN") : "—",
    lastRun: null,
  }));

  return (
    <div className="p-4">
      <div className="flex items-center justify-between mb-4">
        <span className="text-xs text-text-secondary">{saved.length} flow{saved.length !== 1 ? "s" : ""} saved</span>
        <div className="flex items-center gap-2">
          <Button
            size="sm"
            variant="outline"
            className="h-7 bg-surface-card border-border-default text-text-secondary hover:text-text-primary text-xs gap-1"
            onClick={onFromTemplate}
          >
            <Package size={11} />
            From Template
          </Button>
          <Button
            size="sm"
            className="h-7 bg-primary hover:bg-primary/90 text-white text-xs gap-1"
            onClick={onNew}
          >
            <Plus size={11} />
            New Flow
          </Button>
        </div>
      </div>

      {saved.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-14 text-center">
          <div className="w-14 h-14 rounded-full bg-surface-card border border-border-default flex items-center justify-center mb-4">
            <Workflow size={20} className="text-text-muted" />
          </div>
          <h3 className="text-sm font-medium text-text-primary mb-1">No flows yet</h3>
          <p className="text-xs text-text-muted mb-5 max-w-xs">
            Create your first automation flow. Start from a template or build from scratch using 54 pre-built nodes.
          </p>
          <div className="flex items-center gap-2">
            <Button
              size="sm"
              className="h-8 bg-primary hover:bg-primary/90 text-white text-xs gap-1"
              onClick={onNew}
            >
              <Plus size={13} />
              New Flow
            </Button>
            <Button
              size="sm"
              variant="outline"
              className="h-8 bg-surface-card border-border-default text-text-secondary hover:text-text-primary text-xs gap-1"
              onClick={onFromTemplate}
            >
              <Package size={13} />
              From Template
            </Button>
          </div>
        </div>
      ) : (
        <div className="grid gap-2">
          {saved.map((flow) => (
            <Card
              key={flow.id}
              className="bg-surface-card border-border-default hover:border-border-default transition-colors cursor-default"
            >
              <CardContent className="p-3">
                <div className="flex items-start justify-between">
                  <div className="flex items-center gap-2">
                    <StatusIcon status={flow.status} />
                    <span className="text-sm font-medium text-text-primary">{flow.name}</span>
                  </div>
                  <span className="text-xs text-text-muted">{flow.updatedAt}</span>
                </div>
                <div className="flex items-center gap-3 mt-2 ml-5 text-xs text-text-muted">
                  <span>{flow.nodeCount} nodes</span>
                  <span>{flow.edgeCount} edges</span>
                </div>
                <div className="flex items-center gap-2 mt-2 ml-5">
                  <Button
                    size="sm"
                    variant="ghost"
                    className="h-6 px-2 text-xs text-primary hover:text-white gap-1"
                    onClick={() => onOpen(flow.id)}
                  >
                    <FolderOpen size={11} />
                    Open
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    className="h-6 px-2 text-xs text-red-400 hover:text-red-300 gap-1"
                    onClick={() => onDelete(flow.id)}
                  >
                    <Trash2 size={11} />
                    Delete
                  </Button>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Templates Tab
// ---------------------------------------------------------------------------

interface TemplatesTabProps {
  onUse: (template: FlowTemplate) => void;
}

function TemplatesTab({ onUse }: TemplatesTabProps) {
  const categories = [...new Set(FLOW_TEMPLATES.map((t) => t.category))];
  const [activeCategory, setActiveCategory] = useState("All");

  const filtered =
    activeCategory === "All"
      ? FLOW_TEMPLATES
      : FLOW_TEMPLATES.filter((t) => t.category === activeCategory);

  return (
    <div className="p-4">
      {/* Category filter pills */}
      <div className="flex items-center gap-1.5 flex-wrap mb-4">
        {["All", ...categories].map((cat) => (
          <button
            key={cat}
            onClick={() => setActiveCategory(cat)}
            className={[
              "text-xs px-2.5 py-0.5 rounded-full border transition-colors",
              activeCategory === cat
                ? "bg-neutral-bg text-primary border-neutral-border"
                : "bg-surface-card text-text-muted border-border-default hover:border-border-strong",
            ].join(" ")}
          >
            {cat}
          </button>
        ))}
      </div>

      <div className="grid gap-3">
        {filtered.map((tmpl) => (
          <Card
            key={tmpl.id}
            className="bg-surface-card border-border-default hover:border-border-default transition-colors"
          >
            <CardHeader className="pt-3 pb-1 px-3">
              <div className="flex items-start justify-between gap-2">
                <CardTitle className="text-sm font-medium text-text-primary leading-tight">
                  {tmpl.name}
                </CardTitle>
                <div className="flex items-center gap-1.5 shrink-0 mt-0.5">
                  <DifficultyBadge level={tmpl.difficulty} />
                </div>
              </div>
            </CardHeader>
            <CardContent className="px-3 pb-3">
              <p className="text-xs text-text-muted mb-2 leading-relaxed">{tmpl.description}</p>
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-1.5 flex-wrap">
                  {tmpl.tags.slice(0, 3).map((tag) => (
                    <Badge key={tag} className="text-xxs h-4 px-1.5 bg-border-default text-text-secondary border-border-default">
                      {tag}
                    </Badge>
                  ))}
                  <span className="text-xs text-text-muted">{tmpl.nodeCount} nodes</span>
                </div>
                <Button
                  size="sm"
                  variant="ghost"
                  className="h-6 px-2 text-xs text-text-muted hover:text-text-primary gap-1"
                  onClick={() => onUse(tmpl)}
                  disabled={tmpl.workflow.nodes.length === 0 && tmpl.id !== "simple_market_order" && tmpl.id !== "price_alert_order" && tmpl.id !== "intraday_time_strategy"}
                >
                  Use template
                  <ChevronRight size={11} />
                </Button>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// How It Works Tab — node category reference
// ---------------------------------------------------------------------------

function HowItWorksTab() {
  const totalNodes = NODE_CATEGORIES.reduce((sum, c) => sum + c.nodes.length, 0);

  return (
    <ScrollArea className="h-full">
      <div className="p-4 space-y-5">
        {/* Overview */}
        <Card className="bg-surface-card border-border-default">
          <CardContent className="p-4">
            <div className="flex items-center gap-2 mb-2">
              <Package size={14} className="text-primary" />
              <span className="text-sm font-medium text-text-primary">
                {totalNodes}-Node Flow Builder
              </span>
            </div>
            <p className="text-xs text-text-secondary leading-relaxed">
              FlowBuilder is a visual no-code workflow engine for OpenAlgo. Connect nodes on a
              drag-and-drop canvas to create trading automations — from simple TradingView webhooks
              to complex multi-leg options strategies. Flows run on the FlintTrade Python backend
              against your connected broker via OpenAlgo.
            </p>
            <div className="mt-3 grid grid-cols-4 gap-2 text-center">
              {[["4", "Triggers"], ["10", "Actions"], ["5", "Conditions"], ["3", "Logic"]].map(([count, label]) => (
                <div key={label} className="rounded-md bg-surface-base p-2">
                  <div className="text-base font-mono font-bold text-primary">{count}</div>
                  <div className="text-xs text-text-muted">{label}</div>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>

        {/* Canvas usage tips */}
        <Card className="bg-surface-card border-border-default">
          <CardContent className="p-3">
            <div className="text-xs font-semibold text-text-primary mb-2">Canvas Controls</div>
            <div className="grid gap-1">
              {[
                ["Drag from palette", "Drop a node onto the canvas"],
                ["Drag node", "Move it around"],
                ["Port circle (bottom)", "Drag from output to input to connect"],
                ["Click edge", "Delete the connection"],
                ["Click node", "Opens config panel on the right"],
                ["Scroll / pinch", "Zoom in and out"],
                ["Drag blank area", "Pan the canvas"],
                ["Delete in config panel", "Remove the selected node"],
              ].map(([k, v]) => (
                <div key={k} className="flex items-start gap-2 text-xs py-1 border-b border-border-default last:border-none">
                  <span className="text-primary font-mono shrink-0 w-36">{k}</span>
                  <span className="text-text-secondary">{v}</span>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>

        {/* Node categories */}
        {NODE_CATEGORIES.map((cat) => (
          <div key={cat.id}>
            <div className="flex items-center gap-2 mb-2" style={{ color: cat.color }}>
              {cat.icon}
              <span className="text-xs font-semibold">{cat.label}</span>
              <Badge className="text-xxs h-4 px-1.5 bg-surface-card text-text-muted border-border-default">
                {cat.nodes.length} nodes
              </Badge>
            </div>
            <div className="grid gap-1">
              {cat.nodes.map((node) => (
                <div
                  key={node.type}
                  className="flex items-start gap-2 rounded-md bg-surface-card border border-border-default px-3 py-2"
                >
                  <div className="w-1.5 h-1.5 rounded-full mt-1.5 shrink-0" style={{ backgroundColor: cat.color }} />
                  <div>
                    <span className="text-xs text-text-primary font-medium">{node.label}</span>
                    <span className="text-xs text-text-muted ml-2">{node.description}</span>
                  </div>
                </div>
              ))}
            </div>
          </div>
        ))}

        {/* Backend note */}
        <Card className="bg-atm-bg border-atm-border">
          <CardContent className="p-3 flex items-start gap-2">
            <Info size={13} className="text-amber-400 mt-0.5 shrink-0" />
            <p className="text-xs text-text-secondary">
              Execution requires the FlintTrade Python backend (
              <span className="font-mono text-amber-400">packages/automation</span>). The canvas
              editor is fully functional — save flows as JSON and load them into the runner when
              the backend is connected.
            </p>
          </CardContent>
        </Card>
      </div>
    </ScrollArea>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

interface Props {
  onClose?: () => void;
}

type View = "list" | "editor" | "templates";

export default function FlowBuilderTool({ onClose }: Props) {
  const [stored, setStored] = useState<StoredData>(loadStored);
  const [view, setView] = useState<View>("list");
  const [activeFlowId, setActiveFlowId] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState("flows");

  function persist(next: StoredData) {
    setStored(next);
    saveStored(next);
  }

  function handleNewFlow() {
    const id = `flow_${Date.now()}`;
    const newFlow: FlowWorkflow = {
      id,
      name: "New Flow",
      nodes: [],
      edges: [],
      updatedAt: new Date().toISOString(),
    };
    persist({ flows: [...stored.flows, newFlow] });
    setActiveFlowId(id);
    setView("editor");
  }

  function handleOpenFlow(id: string) {
    setActiveFlowId(id);
    setView("editor");
  }

  function handleDeleteFlow(id: string) {
    persist({ flows: stored.flows.filter((f) => f.id !== id) });
    if (activeFlowId === id) { setActiveFlowId(null); setView("list"); }
  }

  function handleSaveFlow(updated: FlowWorkflow) {
    persist({ flows: stored.flows.map((f) => f.id === updated.id ? updated : f) });
  }

  function handleUseTemplate(tmpl: FlowTemplate) {
    if (tmpl.workflow.nodes.length === 0) return;
    const id = `flow_${Date.now()}`;
    const newFlow: FlowWorkflow = {
      id,
      name: tmpl.name,
      nodes: tmpl.workflow.nodes.map((n) => ({ ...n, id: genNodeId() })),
      edges: [],
      updatedAt: new Date().toISOString(),
    };
    // Re-wire edges using new node IDs — build old→new map
    const oldIds = tmpl.workflow.nodes.map((n) => n.id);
    const newIds = newFlow.nodes.map((n) => n.id);
    const idMap = new Map<string, string>();
    oldIds.forEach((old, i) => idMap.set(old, newIds[i]));
    newFlow.edges = tmpl.workflow.edges.map((e) => ({
      id: genEdgeId(),
      sourceId: idMap.get(e.sourceId) ?? e.sourceId,
      targetId: idMap.get(e.targetId) ?? e.targetId,
      sourcePort: e.sourcePort,
      targetPort: e.targetPort,
    }));
    persist({ flows: [...stored.flows, newFlow] });
    setActiveFlowId(id);
    setView("editor");
  }

  const activeFlow = stored.flows.find((f) => f.id === activeFlowId) ?? null;

  // Editor view — full screen
  if (view === "editor" && activeFlow) {
    return (
      <div className="h-full flex flex-col bg-surface-base">
        <EditorView
          flow={activeFlow}
          onSave={handleSaveFlow}
          onBack={() => setView("list")}
        />
      </div>
    );
  }

  // List / templates view
  return (
    <div className="h-full flex flex-col bg-surface-base">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-2.5 border-b border-border-default bg-surface-card shrink-0">
        <div className="flex items-center gap-2">
          <Workflow size={16} className="text-primary" />
          <span className="font-heading font-bold text-lg text-text-primary">Flow Builder</span>
          <Badge className="text-xxs h-4 px-1.5 bg-bullish-bg text-emerald-400 border-bullish-border">
            54 nodes
          </Badge>
        </div>
        <button
          onClick={onClose}
          className="text-text-muted hover:text-text-primary transition-colors"
        >
          <X size={15} />
        </button>
      </div>

      {/* Tabs */}
      <Tabs value={activeTab} onValueChange={setActiveTab} className="flex flex-col flex-1 min-h-0">
        <TabsList className="mx-4 mt-3 mb-0 h-8 bg-surface-card border border-border-default shrink-0 rounded-md w-auto self-start">
          <TabsTrigger
            value="flows"
            className="text-xs font-medium h-6 px-3 data-[state=active]:bg-surface-elevated data-[state=active]:text-text-primary"
          >
            Flows
          </TabsTrigger>
          <TabsTrigger
            value="templates"
            className="text-xs font-medium h-6 px-3 data-[state=active]:bg-surface-elevated data-[state=active]:text-text-primary"
          >
            Templates
          </TabsTrigger>
          <TabsTrigger
            value="how"
            className="text-xs font-medium h-6 px-3 data-[state=active]:bg-surface-elevated data-[state=active]:text-text-primary"
          >
            How It Works
          </TabsTrigger>
        </TabsList>

        <TabsContent value="flows" className="flex-1 overflow-y-auto mt-0">
          <FlowsTab
            flows={stored.flows}
            onNew={handleNewFlow}
            onOpen={handleOpenFlow}
            onDelete={handleDeleteFlow}
            onFromTemplate={() => setActiveTab("templates")}
          />
        </TabsContent>
        <TabsContent value="templates" className="flex-1 overflow-y-auto mt-0">
          <TemplatesTab onUse={handleUseTemplate} />
        </TabsContent>
        <TabsContent value="how" className="flex-1 overflow-y-auto mt-0">
          <HowItWorksTab />
        </TabsContent>
      </Tabs>
    </div>
  );
}
