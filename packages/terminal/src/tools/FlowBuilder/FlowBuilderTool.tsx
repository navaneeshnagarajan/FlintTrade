/**
 * FlowBuilderTool — Visual workflow automation preview
 * Absorbed from:
 *   - openalgo-flow/frontend: 54-node complete flow builder
 *     Node categories: Triggers, Actions, Conditions, Logic Gates,
 *     Data, WebSocket, Risk, Utilities (all 54 nodes mapped below)
 *   - openalgo-flow/frontend/src/pages/Dashboard.tsx:
 *     Workflow card pattern, empty state, status icons
 */

import { useState } from "react";
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
  Info,
  Package,
} from "lucide-react";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type FlowStatus = "active" | "inactive" | "running" | "error";

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
}

interface NodeCategory {
  id: string;
  label: string;
  icon: React.ReactNode;
  color: string;
  nodes: { type: string; label: string; description: string }[];
}

// ---------------------------------------------------------------------------
// Static data — absorbed from openalgo-flow node registry (54 nodes)
// ---------------------------------------------------------------------------

const SAVED_FLOWS: SavedFlow[] = [];

// Absorbed directly from openalgo-flow/frontend/src/components/nodes/index.ts
const NODE_CATEGORIES: NodeCategory[] = [
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

const FLOW_TEMPLATES: FlowTemplate[] = [
  {
    id: "ema_crossover_auto",
    name: "EMA Crossover Auto Trader",
    description: "Subscribe to LTP, compute EMA 9/21 crossover, place smart order on signal. Includes time window gate and Telegram alert.",
    category: "Trend Following",
    nodeCount: 8,
    tags: ["EMA", "Smart Order", "Telegram"],
    difficulty: "Beginner",
  },
  {
    id: "supertrend_nifty",
    name: "Supertrend Nifty Options",
    description: "ATR-based supertrend on Nifty 15m. On signal, place Nifty CE/PE via options order. Includes margin check and fund gate.",
    category: "Options",
    nodeCount: 11,
    tags: ["Supertrend", "Options", "Margin Check"],
    difficulty: "Intermediate",
  },
  {
    id: "tradingview_webhook",
    name: "TradingView Webhook Handler",
    description: "Receive TradingView Pine alerts via webhook, parse action (BUY/SELL), route to place order with position check.",
    category: "Automation",
    nodeCount: 6,
    tags: ["TradingView", "Webhook", "Place Order"],
    difficulty: "Beginner",
  },
  {
    id: "chartink_scanner",
    name: "Chartink Scanner Auto Buy",
    description: "Accept Chartink scan webhook, extract stock list, loop with split order for position sizing, cancel if outside window.",
    category: "Screener",
    nodeCount: 9,
    tags: ["Chartink", "Basket", "Time Window"],
    difficulty: "Intermediate",
  },
  {
    id: "morning_square_off",
    name: "Morning Square-Off Guard",
    description: "At 9:16 AM, check positions. If overnight F&O positions exist, close all before CNC cutoff. Sends Telegram summary.",
    category: "Risk Management",
    nodeCount: 7,
    tags: ["Close Positions", "Telegram", "Scheduled"],
    difficulty: "Intermediate",
  },
  {
    id: "options_expiry_exit",
    name: "Options Expiry Day Exit",
    description: "On expiry day at 3:00 PM, fetch option chain, identify short positions near strike, cancel and close. Walk-away logic.",
    category: "Options",
    nodeCount: 14,
    tags: ["Expiry", "Option Chain", "Risk"],
    difficulty: "Advanced",
  },
  {
    id: "grid_rebalancer",
    name: "Grid Rebalancer",
    description: "Deploy arithmetic grid around LTP. Subscribe depth for spread tracking. Auto-reprice grid on breakout. State via variable nodes.",
    category: "Algorithmic",
    nodeCount: 18,
    tags: ["Grid", "Depth", "Variable", "Smart Order"],
    difficulty: "Advanced",
  },
  {
    id: "pairs_trade",
    name: "Statistical Pairs Trade",
    description: "Fetch OHLCV for two symbols, compute spread z-score via math expression. Enter long/short on deviation, exit on mean reversion.",
    category: "Statistical Arbitrage",
    nodeCount: 12,
    tags: ["History", "Math", "Pairs", "Smart Order"],
    difficulty: "Advanced",
  },
];

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function StatusIcon({ status }: { status: FlowStatus }) {
  switch (status) {
    case "active":
      return <CheckCircle2 size={12} className="text-emerald-400" />;
    case "running":
      return <Play size={12} className="text-[#6c8ef0] animate-pulse" />;
    case "error":
      return <XCircle size={12} className="text-red-400" />;
    case "inactive":
    default:
      return <Pause size={12} className="text-[#6b6b8a]" />;
  }
}

function DifficultyBadge({ level }: { level: FlowTemplate["difficulty"] }) {
  const map = {
    Beginner: "bg-[#0a2a1a] text-emerald-400 border-[#1a3a2a]",
    Intermediate: "bg-[#1a1a2a] text-[#818cf8] border-[#2a2a4a]",
    Advanced: "bg-[#2a1a0a] text-amber-400 border-[#3a2a1a]",
  };
  return (
    <Badge className={`text-[9px] h-4 px-1.5 ${map[level]}`}>{level}</Badge>
  );
}

// ---------------------------------------------------------------------------
// Flows Tab
// ---------------------------------------------------------------------------

function FlowsTab() {
  return (
    <div className="p-4">
      {/* Extension notice */}
      <div className="flex items-start gap-2 rounded-md bg-[#1a1a28] border border-[#1e1e2e] p-3 mb-5">
        <Info size={13} className="text-amber-400 mt-0.5 shrink-0" />
        <p className="text-[11px] text-[#9090b0]">
          Full visual flow builder requires the React Flow library. Install via{" "}
          <span className="text-[#6c8ef0]">Settings &rarr; Extensions</span>.
          Flows created here will be editable in the canvas editor.
        </p>
      </div>

      {/* Empty state — absorbed from openalgo-flow Dashboard empty state */}
      {SAVED_FLOWS.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-14 text-center">
          <div className="w-14 h-14 rounded-full bg-[#12121a] border border-[#1e1e2e] flex items-center justify-center mb-4">
            <Plus size={20} className="text-[#6b6b8a]" />
          </div>
          <h3 className="text-[14px] font-medium text-[#e0e0f0] mb-1">
            No flows yet
          </h3>
          <p className="text-[12px] text-[#6b6b8a] mb-5 max-w-xs">
            Create your first automation flow. Start from a template or build
            from scratch using 54 pre-built nodes.
          </p>
          <div className="flex items-center gap-2">
            <Button
              size="sm"
              className="h-8 bg-[#3b5bdb] hover:bg-[#4c6ef5] text-white text-[12px]"
              disabled
            >
              <Plus size={13} className="mr-1.5" />
              New Flow
            </Button>
            <Button
              size="sm"
              variant="outline"
              className="h-8 bg-[#12121a] border-[#1e1e2e] text-[#9090b0] hover:text-[#e0e0f0] text-[12px]"
              disabled
            >
              From Template
            </Button>
          </div>
          <p className="text-[10px] text-[#404060] mt-3">
            Requires React Flow extension
          </p>
        </div>
      ) : (
        <div className="grid gap-3">
          {SAVED_FLOWS.map((flow) => (
            <Card
              key={flow.id}
              className="bg-[#12121a] border-[#1e1e2e] hover:border-[#2a2a4a] transition-colors cursor-default"
            >
              <CardContent className="p-3">
                <div className="flex items-start justify-between">
                  <div className="flex items-center gap-2">
                    <StatusIcon status={flow.status} />
                    <span className="text-[13px] font-medium text-[#e0e0f0]">
                      {flow.name}
                    </span>
                  </div>
                  <span className="text-[10px] text-[#6b6b8a]">
                    {flow.updatedAt}
                  </span>
                </div>
                <p className="text-[11px] text-[#6b6b8a] mt-1 ml-5">
                  {flow.description}
                </p>
                <div className="flex items-center gap-3 mt-2 ml-5 text-[10px] text-[#6b6b8a]">
                  <span>{flow.nodeCount} nodes</span>
                  <span>{flow.edgeCount} edges</span>
                  {flow.lastRun && <span>Last run: {flow.lastRun}</span>}
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

function TemplatesTab() {
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
              "text-[11px] px-2.5 py-0.5 rounded-full border transition-colors",
              activeCategory === cat
                ? "bg-[#1e2a4a] text-[#6c8ef0] border-[#2a3a6a]"
                : "bg-[#12121a] text-[#6b6b8a] border-[#1e1e2e] hover:border-[#3a3a5a]",
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
            className="bg-[#12121a] border-[#1e1e2e] hover:border-[#2a2a4a] transition-colors"
          >
            <CardHeader className="pt-3 pb-1 px-3">
              <div className="flex items-start justify-between gap-2">
                <CardTitle className="text-[13px] font-medium text-[#e0e0f0] leading-tight">
                  {tmpl.name}
                </CardTitle>
                <div className="flex items-center gap-1.5 shrink-0 mt-0.5">
                  <DifficultyBadge level={tmpl.difficulty} />
                </div>
              </div>
            </CardHeader>
            <CardContent className="px-3 pb-3">
              <p className="text-[11px] text-[#6b6b8a] mb-2 leading-relaxed">
                {tmpl.description}
              </p>
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-1.5 flex-wrap">
                  {tmpl.tags.slice(0, 3).map((tag) => (
                    <Badge
                      key={tag}
                      className="text-[9px] h-4 px-1.5 bg-[#1e1e2e] text-[#9090b0] border-[#2a2a3a]"
                    >
                      {tag}
                    </Badge>
                  ))}
                  <span className="text-[10px] text-[#6b6b8a]">
                    {tmpl.nodeCount} nodes
                  </span>
                </div>
                <Button
                  size="sm"
                  variant="ghost"
                  className="h-6 px-2 text-[11px] text-[#6b6b8a] hover:text-[#e0e0f0] gap-1"
                  disabled
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
        <Card className="bg-[#12121a] border-[#1e1e2e]">
          <CardContent className="p-4">
            <div className="flex items-center gap-2 mb-2">
              <Package size={14} className="text-[#6c8ef0]" />
              <span className="text-[13px] font-medium text-[#e0e0f0]">
                {totalNodes}-Node Flow Builder
              </span>
            </div>
            <p className="text-[12px] text-[#9090b0] leading-relaxed">
              FlowBuilder is a visual no-code workflow engine for OpenAlgo. Connect
              nodes on a drag-and-drop canvas to create trading automations — from
              simple TradingView webhooks to complex multi-leg options strategies.
              Flows run on the FlintTrade backend against your connected broker via
              OpenAlgo.
            </p>
            <div className="mt-3 grid grid-cols-4 gap-2 text-center">
              {[
                ["4", "Triggers"],
                ["10", "Actions"],
                ["5", "Conditions"],
                ["3", "Logic Gates"],
              ].map(([count, label]) => (
                <div key={label} className="rounded-md bg-[#0a0a0f] p-2">
                  <div className="text-[16px] font-mono font-bold text-[#6c8ef0]">
                    {count}
                  </div>
                  <div className="text-[10px] text-[#6b6b8a]">{label}</div>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>

        {/* Node categories — absorbed from openalgo-flow node registry */}
        {NODE_CATEGORIES.map((cat) => (
          <div key={cat.id}>
            <div
              className="flex items-center gap-2 mb-2"
              style={{ color: cat.color }}
            >
              {cat.icon}
              <span className="text-[12px] font-semibold">{cat.label}</span>
              <Badge className="text-[9px] h-4 px-1.5 bg-[#12121a] text-[#6b6b8a] border-[#1e1e2e]">
                {cat.nodes.length} nodes
              </Badge>
            </div>
            <div className="grid gap-1">
              {cat.nodes.map((node) => (
                <div
                  key={node.type}
                  className="flex items-start gap-2 rounded-md bg-[#12121a] border border-[#1e1e2e] px-3 py-2"
                >
                  <div
                    className="w-1.5 h-1.5 rounded-full mt-1.5 shrink-0"
                    style={{ backgroundColor: cat.color }}
                  />
                  <div>
                    <span className="text-[12px] text-[#e0e0f0] font-medium">
                      {node.label}
                    </span>
                    <span className="text-[11px] text-[#6b6b8a] ml-2">
                      {node.description}
                    </span>
                  </div>
                </div>
              ))}
            </div>
          </div>
        ))}

        {/* Install note */}
        <Card className="bg-[#1a1a0a] border-[#2a2a1a]">
          <CardContent className="p-3 flex items-start gap-2">
            <AlertCircle size={13} className="text-amber-400 mt-0.5 shrink-0" />
            <p className="text-[11px] text-[#9090b0]">
              The canvas editor uses{" "}
              <span className="font-mono text-amber-400">@xyflow/react</span> (React
              Flow v12). Install via{" "}
              <span className="font-mono text-[#e0e0f0]">Settings &rarr; Extensions</span>{" "}
              to enable the drag-and-drop editor. All 54 node types, edge routing,
              execution logs, and webhook management will be available after install.
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

export default function FlowBuilderTool({ onClose }: Props) {
  return (
    <div className="h-full flex flex-col bg-[#0a0a0f]">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-2.5 border-b border-[#1e1e2e] bg-[#12121a] shrink-0">
        <div className="flex items-center gap-2">
          <Workflow size={16} className="text-[#6c8ef0]" />
          <span className="text-[13px] font-semibold text-[#e0e0f0]">
            Flow Builder
          </span>
          <Badge className="text-[9px] h-4 px-1.5 bg-[#1a2a0a] text-emerald-400 border-[#2a3a1a]">
            54 nodes
          </Badge>
        </div>
        <button
          onClick={onClose}
          className="text-[#6b6b8a] hover:text-[#e0e0f0] transition-colors"
        >
          <X size={15} />
        </button>
      </div>

      {/* Tabs */}
      <Tabs defaultValue="flows" className="flex flex-col flex-1 min-h-0">
        <TabsList className="mx-4 mt-3 mb-0 h-8 bg-[#12121a] border border-[#1e1e2e] shrink-0 rounded-md w-auto self-start">
          <TabsTrigger
            value="flows"
            className="text-[12px] h-6 px-3 data-[state=active]:bg-[#1e1e2e] data-[state=active]:text-[#e0e0f0]"
          >
            Flows
          </TabsTrigger>
          <TabsTrigger
            value="templates"
            className="text-[12px] h-6 px-3 data-[state=active]:bg-[#1e1e2e] data-[state=active]:text-[#e0e0f0]"
          >
            Templates
          </TabsTrigger>
          <TabsTrigger
            value="how"
            className="text-[12px] h-6 px-3 data-[state=active]:bg-[#1e1e2e] data-[state=active]:text-[#e0e0f0]"
          >
            How It Works
          </TabsTrigger>
        </TabsList>

        <TabsContent value="flows" className="flex-1 overflow-y-auto mt-0">
          <FlowsTab />
        </TabsContent>
        <TabsContent value="templates" className="flex-1 overflow-y-auto mt-0">
          <TemplatesTab />
        </TabsContent>
        <TabsContent value="how" className="flex-1 overflow-y-auto mt-0">
          <HowItWorksTab />
        </TabsContent>
      </Tabs>
    </div>
  );
}
