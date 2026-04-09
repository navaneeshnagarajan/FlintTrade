/**
 * FlowBuilderTool — Visual workflow automation builder
 *
 * Canvas powered by @xyflow/react v12 (React Flow).
 * Layout:
 *   - Left: NodePalette (categorised + searchable draggable nodes)
 *   - Centre: React Flow canvas with custom BaseNode
 *   - Right: ConfigPanel (shown when a node is selected)
 *   - Bottom: ExecutionLog (collapsible)
 *   - Top: Toolbar (Run, Save, Clear, New Flow, back navigation)
 *
 * State managed via flowStore (Zustand). Persistence via localStorage.
 *
 * 54 nodes across 8 categories:
 *   Triggers · Orders · Conditions · Logic · Data · WebSocket · Account · Integration
 */

import "@xyflow/react/dist/style.css";

import React, { useState, useCallback, type DragEvent } from "react";
import {
  ReactFlow,
  Background,
  BackgroundVariant,
  Controls,
  MiniMap,
  Panel,
} from "@xyflow/react";
import {
  X,
  Workflow,
  Plus,
  Play,
  Save,
  Trash2,
  ChevronRight,
  Terminal,
  Package,
  FolderOpen,
  AlertCircle,
  CheckCircle2,
  XCircle,
  Pause,
  Info,
} from "lucide-react";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";

import { useFlowStore } from "@/stores/flowStore";
import { NodePalette, DRAG_MIME } from "./flow/NodePalette";
import { ConfigPanel } from "./flow/ConfigPanel";
import { ExecutionLog } from "./flow/ExecutionLog";
import { REACT_FLOW_NODE_TYPES } from "./flow/BaseNode";
import {
  NODE_CATEGORIES,
  NODE_TYPE_TO_CATEGORY,
  NODE_TYPE_TO_COLOR,
  NODE_TYPE_TO_LABEL,
  getTotalNodeCount,
} from "./flow/nodeRegistry";
import type { FlowNodeData, SavedWorkflow } from "@/stores/flowStore";
import type { Node } from "@xyflow/react";

// ---------------------------------------------------------------------------
// Flow template data
// ---------------------------------------------------------------------------

type Difficulty = "Beginner" | "Intermediate" | "Advanced";

interface FlowTemplate {
  id: string;
  name: string;
  description: string;
  category: string;
  nodeCount: number;
  tags: string[];
  difficulty: Difficulty;
  workflow: Pick<SavedWorkflow, "nodes" | "edges">;
}

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
    workflow: makePriceAlertWorkflow(),
  },
  {
    id: "intraday_time_strategy",
    name: "Intraday Time Strategy",
    description: "Start → Market open window → Fund check → Smart order entry → Scheduled 3:15 PM square-off.",
    category: "Intraday",
    nodeCount: 6,
    tags: ["Time Window", "Fund Check", "Smart Order", "Close Positions"],
    difficulty: "Intermediate",
    workflow: makeIntradayWorkflow(),
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
    description: "On expiry day at 3:00 PM, fetch option chain, identify short positions near strike, cancel and close.",
    category: "Options",
    nodeCount: 14,
    tags: ["Expiry", "Option Chain", "Risk"],
    difficulty: "Advanced",
    workflow: { nodes: [], edges: [] },
  },
  {
    id: "grid_rebalancer",
    name: "Grid Rebalancer",
    description: "Deploy arithmetic grid around LTP. Subscribe depth for spread tracking. Auto-reprice grid on breakout.",
    category: "Algorithmic",
    nodeCount: 18,
    tags: ["Grid", "Depth", "Variable", "Smart Order"],
    difficulty: "Advanced",
    workflow: { nodes: [], edges: [] },
  },
];

// ---------------------------------------------------------------------------
// Shared micro-components
// ---------------------------------------------------------------------------

type FlowStatus = "active" | "inactive" | "running" | "error";

function StatusIcon({ status }: { status: FlowStatus }) {
  switch (status) {
    case "active":
      return <CheckCircle2 size={12} className="text-emerald-400" />;
    case "running":
      return <Play size={12} className="text-primary animate-pulse" />;
    case "error":
      return <XCircle size={12} className="text-red-400" />;
    default:
      return <Pause size={12} className="text-text-muted" />;
  }
}

function DifficultyBadge({ level }: { level: Difficulty }) {
  const map: Record<Difficulty, string> = {
    Beginner: "bg-bullish-bg text-emerald-400 border-bullish-border",
    Intermediate: "bg-surface-elevated text-primary border-border-default",
    Advanced: "bg-atm-bg text-amber-400 border-atm-border",
  };
  return <Badge className={`text-xxs h-4 px-1.5 ${map[level]}`}>{level}</Badge>;
}

// ---------------------------------------------------------------------------
// React Flow canvas editor (inner — used when editing a specific flow)
// ---------------------------------------------------------------------------

interface FlowCanvasProps {
  flowId: string;
  flowName: string;
  onBack: () => void;
}

function FlowCanvas({ flowId, flowName, onBack }: FlowCanvasProps) {
  const nodes = useFlowStore((s) => s.nodes);
  const edges = useFlowStore((s) => s.edges);
  const selectedNodeId = useFlowStore((s) => s.selectedNodeId);
  const onNodesChange = useFlowStore((s) => s.onNodesChange);
  const onEdgesChange = useFlowStore((s) => s.onEdgesChange);
  const onConnect = useFlowStore((s) => s.onConnect);
  const addNode = useFlowStore((s) => s.addNode);
  const selectNode = useFlowStore((s) => s.selectNode);
  const saveFlowById = useFlowStore((s) => s.saveFlowById);
  const clearCanvas = useFlowStore((s) => s.clearCanvas);
  const addLogEntry = useFlowStore((s) => s.addLogEntry);

  const [name, setName] = useState(flowName);
  const [saved, setSaved] = useState(true);
  const [showRunNote, setShowRunNote] = useState(false);
  const [logCollapsed, setLogCollapsed] = useState(false);

  const selectedNode = nodes.find((n) => n.id === selectedNodeId) ?? null;

  // Handle drag-drop from NodePalette onto React Flow canvas
  const handleDrop = useCallback(
    (e: DragEvent<HTMLDivElement>) => {
      e.preventDefault();
      const nodeType = e.dataTransfer.getData(DRAG_MIME);
      if (!nodeType) return;

      // Use the React Flow wrapper element to compute canvas position
      const bounds = (e.currentTarget as HTMLDivElement).getBoundingClientRect();
      const position = {
        x: e.clientX - bounds.left,
        y: e.clientY - bounds.top,
      };

      const catId = NODE_TYPE_TO_CATEGORY.get(nodeType) ?? "utilities";
      const color = NODE_TYPE_TO_COLOR.get(nodeType) ?? "#a78bfa";
      const label = NODE_TYPE_TO_LABEL.get(nodeType) ?? nodeType;

      addNode(nodeType, position, label, catId, color);
      setSaved(false);
    },
    [addNode]
  );

  const handleDragOver = useCallback((e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = "copy";
  }, []);

  const handleNodeClick = useCallback(
    (_e: React.MouseEvent, node: Node<FlowNodeData>) => {
      selectNode(node.id);
    },
    [selectNode]
  );

  const handlePaneClick = useCallback(() => {
    selectNode(null);
  }, [selectNode]);

  const handleNodesChange: typeof onNodesChange = useCallback(
    (changes) => {
      onNodesChange(changes);
      const hasMutation = changes.some((c) => c.type !== "select" && c.type !== "dimensions");
      if (hasMutation) setSaved(false);
    },
    [onNodesChange]
  );

  const handleEdgesChange: typeof onEdgesChange = useCallback(
    (changes) => {
      onEdgesChange(changes);
      if (changes.length > 0) setSaved(false);
    },
    [onEdgesChange]
  );

  const handleConnect: typeof onConnect = useCallback(
    (connection) => {
      onConnect(connection);
      setSaved(false);
    },
    [onConnect]
  );

  function handleSave(): void {
    saveFlowById(flowId, nodes, edges, name);
    setSaved(true);
    addLogEntry("success", `Workflow "${name}" saved (${nodes.length} nodes, ${edges.length} edges)`);
  }

  function handleRunClick(): void {
    setShowRunNote((v) => !v);
  }

  function handleClear(): void {
    clearCanvas();
    setSaved(false);
  }

  return (
    <div className="flex flex-col h-full" style={{ background: "var(--color-base)" }}>
      {/* Toolbar */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          padding: "6px 12px",
          borderBottom: "1px solid var(--color-border)",
          background: "var(--color-card)",
          flexShrink: 0,
          zIndex: 10,
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <button
            onClick={onBack}
            style={{ color: "var(--color-text-muted)", background: "none", border: "none", cursor: "pointer", padding: 2, display: "flex", alignItems: "center" }}
            aria-label="Back to flow list"
          >
            <ChevronRight size={14} style={{ transform: "rotate(180deg)" }} />
          </button>
          <input
            value={name}
            onChange={(e) => { setName(e.target.value); setSaved(false); }}
            style={{ fontSize: 12, fontWeight: 600, background: "transparent", border: "1px solid transparent", borderRadius: 4, color: "var(--color-text)", padding: "2px 6px", outline: "none" }}
            onMouseEnter={(e) => { (e.currentTarget as HTMLInputElement).style.borderColor = "var(--color-border)"; }}
            onMouseLeave={(e) => { (e.currentTarget as HTMLInputElement).style.borderColor = "transparent"; }}
          />
          {!saved && (
            <span style={{ fontSize: 10, color: "var(--color-text-muted)" }}>Unsaved</span>
          )}
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <span style={{ fontSize: 10, color: "var(--color-text-muted)" }}>
            {nodes.length} nodes · {edges.length} edges
          </span>

          <Button
            size="sm"
            variant="ghost"
            className="h-6 px-2 text-xs text-text-muted hover:text-red-400 gap-1"
            onClick={handleClear}
            title="Clear canvas"
          >
            <Trash2 size={11} />
          </Button>

          <Button
            size="sm"
            variant="ghost"
            className="h-6 px-2 text-xs text-amber-400 hover:text-amber-300 gap-1"
            onClick={handleRunClick}
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
        <div
          style={{
            background: "var(--color-card)",
            borderBottom: "1px solid var(--color-border)",
            padding: "6px 12px",
            display: "flex",
            alignItems: "center",
            gap: 6,
            flexShrink: 0,
          }}
        >
          <AlertCircle size={12} style={{ color: "#f59e0b", flexShrink: 0 }} />
          <span style={{ fontSize: 11, color: "var(--color-text-muted)" }}>
            Connect the Python backend to execute flows. Run{" "}
            <span style={{ fontFamily: "monospace", color: "var(--color-text)" }}>
              python -m packages.automation.src.flow_runner
            </span>{" "}
            and enable execution in Settings.
          </span>
          <button
            onClick={() => setShowRunNote(false)}
            style={{ marginLeft: "auto", color: "var(--color-text-muted)", background: "none", border: "none", cursor: "pointer" }}
          >
            <X size={11} />
          </button>
        </div>
      )}

      {/* Canvas row: palette + React Flow + config panel */}
      <div style={{ flex: 1, display: "flex", minHeight: 0 }}>
        {/* Left: Node palette */}
        <NodePalette />

        {/* Centre: React Flow */}
        <div
          style={{ flex: 1, minWidth: 0 }}
          onDrop={handleDrop}
          onDragOver={handleDragOver}
        >
          <ReactFlow
            nodes={nodes}
            edges={edges}
            nodeTypes={REACT_FLOW_NODE_TYPES}
            onNodesChange={handleNodesChange}
            onEdgesChange={handleEdgesChange}
            onConnect={handleConnect}
            onNodeClick={handleNodeClick}
            onPaneClick={handlePaneClick}
            fitView
            style={{ background: "var(--color-base)" }}
            defaultEdgeOptions={{
              animated: true,
              style: { stroke: "#6c8ef0", strokeWidth: 1.5 },
            }}
            proOptions={{ hideAttribution: true }}
          >
            {/* Dot grid — matches FlintTrade design token bg */}
            <Background
              variant={BackgroundVariant.Dots}
              gap={16}
              size={0.6}
              color="var(--color-border)"
            />

            {/* Controls — zoom in/out/fit/lock */}
            <Controls
              style={{
                background: "var(--color-card)",
                border: "1px solid var(--color-border)",
                borderRadius: 6,
              }}
            />

            {/* Mini-map — bottom right */}
            <MiniMap
              style={{
                background: "var(--color-card)",
                border: "1px solid var(--color-border)",
              }}
              nodeColor={(node: Node<FlowNodeData>) =>
                (node.data as FlowNodeData).color ?? "#6c8ef0"
              }
              maskColor="rgba(0,0,0,0.3)"
            />

            {/* Empty state hint */}
            {nodes.length === 0 && (
              <Panel position="top-center">
                <div
                  style={{
                    marginTop: 80,
                    display: "flex",
                    flexDirection: "column",
                    alignItems: "center",
                    gap: 8,
                    pointerEvents: "none",
                  }}
                >
                  <div
                    style={{
                      width: 48,
                      height: 48,
                      borderRadius: "50%",
                      background: "var(--color-card)",
                      border: "1px solid var(--color-border)",
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "center",
                    }}
                  >
                    <Workflow size={20} style={{ color: "var(--color-text-muted)" }} />
                  </div>
                  <div style={{ fontSize: 13, color: "var(--color-text)" }}>Empty canvas</div>
                  <div style={{ fontSize: 11, color: "var(--color-text-muted)" }}>
                    Drag nodes from the palette to get started
                  </div>
                </div>
              </Panel>
            )}
          </ReactFlow>
        </div>

        {/* Right: Config panel */}
        {selectedNode && (
          <ConfigPanel
            nodeId={selectedNode.id}
            data={selectedNode.data as FlowNodeData}
            onClose={() => selectNode(null)}
          />
        )}
      </div>

      {/* Bottom: Execution log */}
      <ExecutionLog
        collapsed={logCollapsed}
        onToggle={() => setLogCollapsed((v) => !v)}
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Flows tab (list view)
// ---------------------------------------------------------------------------

interface FlowsTabProps {
  onNew: () => void;
  onOpen: (id: string) => void;
  onFromTemplate: () => void;
}

function FlowsTab({ onNew, onOpen, onFromTemplate }: FlowsTabProps) {
  const savedFlows = useFlowStore((s) => s.savedFlows);
  const deleteFlow = useFlowStore((s) => s.deleteFlow);

  return (
    <div className="p-4">
      <div className="flex items-center justify-between mb-4">
        <span className="text-xs text-text-secondary">
          {savedFlows.length} flow{savedFlows.length !== 1 ? "s" : ""} saved
        </span>
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

      {savedFlows.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-14 text-center">
          <div className="w-14 h-14 rounded-full bg-surface-card border border-border-default flex items-center justify-center mb-4">
            <Workflow size={20} className="text-text-muted" />
          </div>
          <h3 className="text-sm font-medium text-text-primary mb-1">No flows yet</h3>
          <p className="text-xs text-text-muted mb-5 max-w-xs">
            Create your first automation flow. Start from a template or build from scratch using{" "}
            {getTotalNodeCount()} pre-built nodes.
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
          {savedFlows.map((flow) => (
            <Card
              key={flow.id}
              className="bg-surface-card border-border-default hover:border-border-strong transition-colors cursor-default"
            >
              <CardContent className="p-3">
                <div className="flex items-start justify-between">
                  <div className="flex items-center gap-2">
                    <StatusIcon status="inactive" />
                    <span className="text-sm font-medium text-text-primary">{flow.name}</span>
                  </div>
                  <span className="text-xs text-text-muted">
                    {flow.updatedAt ? new Date(flow.updatedAt).toLocaleDateString("en-IN") : "—"}
                  </span>
                </div>
                <div className="flex items-center gap-3 mt-2 ml-5 text-xs text-text-muted">
                  <span>{flow.nodes.length} nodes</span>
                  <span>{flow.edges.length} edges</span>
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
                    onClick={() => deleteFlow(flow.id)}
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
// Templates tab
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
          <Card key={tmpl.id} className="bg-surface-card border-border-default transition-colors">
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
                  disabled={tmpl.workflow.nodes.length === 0}
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
// How It Works tab
// ---------------------------------------------------------------------------

function HowItWorksTab() {
  const totalNodes = getTotalNodeCount();

  return (
    <ScrollArea className="h-full">
      <div className="p-4 space-y-5">
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
              {[["4", "Triggers"], ["10", "Orders"], ["5", "Conditions"], ["7", "Logic"]].map(([count, label]) => (
                <div key={label} className="rounded-md bg-surface-base p-2">
                  <div className="text-base font-mono font-bold text-primary">{count}</div>
                  <div className="text-xs text-text-muted">{label}</div>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>

        <Card className="bg-surface-card border-border-default">
          <CardContent className="p-3">
            <div className="text-xs font-semibold text-text-primary mb-2">Canvas Controls</div>
            <div className="grid gap-1">
              {[
                ["Drag from palette", "Drop a node onto the canvas"],
                ["Drag node", "Move it around the canvas"],
                ["Handle (bottom dot)", "Drag from output to input to connect"],
                ["Delete key", "Remove selected node or edge"],
                ["Click node", "Opens config panel on the right"],
                ["Scroll / pinch", "Zoom in and out"],
                ["Drag blank area", "Pan the canvas"],
                ["Controls (bottom left)", "Zoom in, out, fit, and lock"],
                ["Mini-map (bottom right)", "Overview of full canvas"],
              ].map(([k, v]) => (
                <div key={k} className="flex items-start gap-2 text-xs py-1 border-b border-border-default last:border-none">
                  <span className="text-primary font-mono shrink-0 w-36">{k}</span>
                  <span className="text-text-secondary">{v}</span>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>

        {NODE_CATEGORIES.map((cat) => (
          <div key={cat.id}>
            <div className="flex items-center gap-2 mb-2" style={{ color: cat.color }}>
              <div style={{ width: 8, height: 8, borderRadius: "50%", background: cat.color }} />
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

        <Card className="bg-atm-bg border-atm-border">
          <CardContent className="p-3 flex items-start gap-2">
            <Info size={13} className="text-amber-400 mt-0.5 shrink-0" />
            <p className="text-xs text-text-secondary">
              Execution requires the FlintTrade Python backend (
              <span className="font-mono text-amber-400">packages/automation</span>
              ). The canvas editor is fully functional — save flows as JSON and load them into the
              runner when the backend is connected.
            </p>
          </CardContent>
        </Card>
      </div>
    </ScrollArea>
  );
}

// ---------------------------------------------------------------------------
// Main export
// ---------------------------------------------------------------------------

interface Props {
  onClose?: () => void;
}

type View = "list" | "editor";

export default function FlowBuilderTool({ onClose }: Props) {
  const [view, setView] = useState<View>("list");
  const [activeFlowId, setActiveFlowId] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState("flows");

  const createNewFlow = useFlowStore((s) => s.createNewFlow);
  const openFlow = useFlowStore((s) => s.openFlow);
  const savedFlows = useFlowStore((s) => s.savedFlows);
  const loadWorkflowIntoCanvas = useFlowStore((s) => s.loadWorkflowIntoCanvas);
  const saveFlowById = useFlowStore((s) => s.saveFlowById);

  function handleNewFlow(): void {
    const id = createNewFlow("New Flow");
    setActiveFlowId(id);
    setView("editor");
  }

  function handleOpenFlow(id: string): void {
    openFlow(id);
    setActiveFlowId(id);
    setView("editor");
  }

  function handleUseTemplate(tmpl: FlowTemplate): void {
    if (tmpl.workflow.nodes.length === 0) return;

    // Re-map IDs to avoid collisions with existing canvas nodes
    const idMap = new Map<string, string>();
    const remappedNodes = tmpl.workflow.nodes.map((n) => {
      const newId = `n_${Date.now()}_${Math.random().toString(36).slice(2, 6)}`;
      idMap.set(n.id, newId);
      return { ...n, id: newId };
    });
    const remappedEdges = tmpl.workflow.edges.map((e) => ({
      ...e,
      id: `e_${Date.now()}_${Math.random().toString(36).slice(2, 6)}`,
      source: idMap.get(e.source) ?? e.source,
      target: idMap.get(e.target) ?? e.target,
    }));

    const flowId = `flow_${Date.now()}`;
    const workflow: SavedWorkflow = {
      id: flowId,
      name: tmpl.name,
      nodes: remappedNodes as Node<FlowNodeData>[],
      edges: remappedEdges,
      updatedAt: new Date().toISOString(),
    };

    saveFlowById(flowId, workflow.nodes, workflow.edges, workflow.name);
    loadWorkflowIntoCanvas(workflow);
    setActiveFlowId(flowId);
    setView("editor");
  }

  // Editor view — full page canvas
  if (view === "editor" && activeFlowId) {
    const flow = savedFlows.find((f) => f.id === activeFlowId);
    const flowName = flow?.name ?? "Untitled Flow";

    return (
      <div className="h-full flex flex-col bg-surface-base">
        <FlowCanvas
          flowId={activeFlowId}
          flowName={flowName}
          onBack={() => setView("list")}
        />
      </div>
    );
  }

  // List / templates / how-it-works view
  return (
    <div className="h-full flex flex-col bg-surface-base">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-2.5 border-b border-border-default bg-surface-card shrink-0">
        <div className="flex items-center gap-2">
          <Workflow size={16} className="text-primary" />
          <span className="font-heading font-bold text-lg text-text-primary">Flow Builder</span>
          <Badge className="text-xxs h-4 px-1.5 bg-bullish-bg text-emerald-400 border-bullish-border">
            {getTotalNodeCount()} nodes
          </Badge>
        </div>
        {onClose && (
          <button
            onClick={onClose}
            className="text-text-muted hover:text-text-primary transition-colors"
            aria-label="Close Flow Builder"
          >
            <X size={15} />
          </button>
        )}
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
            onNew={handleNewFlow}
            onOpen={handleOpenFlow}
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
