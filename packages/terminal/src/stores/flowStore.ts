/**
 * flowStore.ts — Zustand store for the Flow Builder tool.
 *
 * Manages React Flow nodes/edges, selection, execution state, and
 * localStorage persistence for saved workflows.
 */

import { create } from "zustand";
import {
  applyNodeChanges,
  applyEdgeChanges,
  addEdge,
  type Node,
  type Edge,
  type OnNodesChange,
  type OnEdgesChange,
  type OnConnect,
  type XYPosition,
} from "@xyflow/react";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type LogLevel = "info" | "success" | "warning" | "error";

export interface LogEntry {
  id: string;
  timestamp: string;
  level: LogLevel;
  message: string;
}

export interface FlowNodeData extends Record<string, unknown> {
  label: string;
  nodeType: string;
  category: string;
  color: string;
  config: Record<string, string>;
}

export interface SavedWorkflow {
  id: string;
  name: string;
  nodes: Node<FlowNodeData>[];
  edges: Edge[];
  updatedAt: string;
}

interface StoredData {
  flows: SavedWorkflow[];
}

interface FlowState {
  // React Flow state
  nodes: Node<FlowNodeData>[];
  edges: Edge[];
  selectedNodeId: string | null;
  isRunning: boolean;
  executionLog: LogEntry[];

  // Saved workflows (localStorage)
  savedFlows: SavedWorkflow[];
  activeFlowId: string | null;

  // React Flow handlers
  onNodesChange: OnNodesChange<Node<FlowNodeData>>;
  onEdgesChange: OnEdgesChange;
  onConnect: OnConnect;

  // Node actions
  addNode: (nodeType: string, position: XYPosition, label: string, category: string, color: string) => void;
  removeNode: (id: string) => void;
  selectNode: (id: string | null) => void;
  updateNodeConfig: (id: string, config: Record<string, string>) => void;
  updateNodeLabel: (id: string, label: string) => void;

  // Canvas actions
  loadWorkflowIntoCanvas: (workflow: SavedWorkflow) => void;
  clearCanvas: () => void;

  // Persistence actions
  saveCurrentFlow: (name: string) => void;
  createNewFlow: (name: string) => string;
  deleteFlow: (id: string) => void;
  openFlow: (id: string) => void;
  saveFlowById: (id: string, nodes: Node<FlowNodeData>[], edges: Edge[], name: string) => void;

  // Execution log
  addLogEntry: (level: LogLevel, message: string) => void;
  clearLog: () => void;
  setRunning: (running: boolean) => void;
}

// ---------------------------------------------------------------------------
// LocalStorage helpers
// ---------------------------------------------------------------------------

const LS_KEY = "flinttrade_flowbuilder_v2";

function loadStored(): StoredData {
  try {
    const raw = localStorage.getItem(LS_KEY);
    if (raw) {
      const parsed: unknown = JSON.parse(raw);
      if (parsed && typeof parsed === "object" && Array.isArray((parsed as StoredData).flows)) {
        return parsed as StoredData;
      }
    }
  } catch {
    // corrupt localStorage — ignore
  }
  return { flows: [] };
}

function saveStored(data: StoredData): void {
  try {
    localStorage.setItem(LS_KEY, JSON.stringify(data));
  } catch {
    // ignore quota errors
  }
}

let logCounter = 1;
function genLogId(): string {
  return `log_${logCounter++}`;
}

// ---------------------------------------------------------------------------
// Store
// ---------------------------------------------------------------------------

const initial = loadStored();

export const useFlowStore = create<FlowState>((set, get) => ({
  nodes: [],
  edges: [],
  selectedNodeId: null,
  isRunning: false,
  executionLog: [],
  savedFlows: initial.flows,
  activeFlowId: null,

  // --- React Flow built-in handlers ---

  onNodesChange: (changes) => {
    set((state) => ({
      nodes: applyNodeChanges(changes, state.nodes),
    }));
  },

  onEdgesChange: (changes) => {
    set((state) => ({
      edges: applyEdgeChanges(changes, state.edges),
    }));
  },

  onConnect: (connection) => {
    set((state) => ({
      edges: addEdge(
        { ...connection, animated: true, style: { stroke: "#6c8ef0", strokeWidth: 1.5 } },
        state.edges
      ),
    }));
  },

  // --- Node actions ---

  addNode: (nodeType, position, label, category, color) => {
    const id = `n_${Date.now()}_${Math.random().toString(36).slice(2, 7)}`;
    // Custom canvas renderers for specific node types; falls back to generic flowNode.
    const rfNodeType = nodeType === "priceAlert" ? "priceAlertNode" : "flowNode";
    const newNode: Node<FlowNodeData> = {
      id,
      type: rfNodeType,
      position,
      data: {
        label,
        nodeType,
        category,
        color,
        config: {},
      },
    };
    set((state) => ({ nodes: [...state.nodes, newNode] }));
  },

  removeNode: (id) => {
    set((state) => ({
      nodes: state.nodes.filter((n) => n.id !== id),
      edges: state.edges.filter((e) => e.source !== id && e.target !== id),
      selectedNodeId: state.selectedNodeId === id ? null : state.selectedNodeId,
    }));
  },

  selectNode: (id) => {
    set({ selectedNodeId: id });
  },

  updateNodeConfig: (id, config) => {
    set((state) => ({
      nodes: state.nodes.map((n) =>
        n.id === id ? { ...n, data: { ...n.data, config } } : n
      ),
    }));
  },

  updateNodeLabel: (id, label) => {
    set((state) => ({
      nodes: state.nodes.map((n) =>
        n.id === id ? { ...n, data: { ...n.data, label } } : n
      ),
    }));
  },

  // --- Canvas actions ---

  loadWorkflowIntoCanvas: (workflow) => {
    set({
      nodes: workflow.nodes,
      edges: workflow.edges,
      selectedNodeId: null,
      activeFlowId: workflow.id,
    });
  },

  clearCanvas: () => {
    set({ nodes: [], edges: [], selectedNodeId: null });
  },

  // --- Persistence ---

  saveCurrentFlow: (name) => {
    const { nodes, edges, activeFlowId, savedFlows } = get();
    if (!activeFlowId) return;
    const updated: SavedWorkflow = {
      id: activeFlowId,
      name,
      nodes,
      edges,
      updatedAt: new Date().toISOString(),
    };
    const nextFlows = savedFlows.map((f) => (f.id === activeFlowId ? updated : f));
    set({ savedFlows: nextFlows });
    saveStored({ flows: nextFlows });
  },

  saveFlowById: (id, nodes, edges, name) => {
    const { savedFlows } = get();
    const updated: SavedWorkflow = {
      id,
      name,
      nodes,
      edges,
      updatedAt: new Date().toISOString(),
    };
    const exists = savedFlows.some((f) => f.id === id);
    const nextFlows = exists
      ? savedFlows.map((f) => (f.id === id ? updated : f))
      : [...savedFlows, updated];
    set({ savedFlows: nextFlows });
    saveStored({ flows: nextFlows });
  },

  createNewFlow: (name) => {
    const id = `flow_${Date.now()}`;
    const newFlow: SavedWorkflow = {
      id,
      name,
      nodes: [],
      edges: [],
      updatedAt: new Date().toISOString(),
    };
    const { savedFlows } = get();
    const nextFlows = [...savedFlows, newFlow];
    set({ savedFlows: nextFlows, activeFlowId: id, nodes: [], edges: [], selectedNodeId: null });
    saveStored({ flows: nextFlows });
    return id;
  },

  deleteFlow: (id) => {
    const { savedFlows, activeFlowId } = get();
    const nextFlows = savedFlows.filter((f) => f.id !== id);
    set({
      savedFlows: nextFlows,
      activeFlowId: activeFlowId === id ? null : activeFlowId,
    });
    saveStored({ flows: nextFlows });
  },

  openFlow: (id) => {
    const { savedFlows } = get();
    const flow = savedFlows.find((f) => f.id === id);
    if (!flow) return;
    set({
      nodes: flow.nodes,
      edges: flow.edges,
      selectedNodeId: null,
      activeFlowId: id,
    });
  },

  // --- Execution log ---

  addLogEntry: (level, message) => {
    const entry: LogEntry = {
      id: genLogId(),
      timestamp: new Date().toLocaleTimeString("en-IN", { hour12: false }),
      level,
      message,
    };
    set((state) => ({
      executionLog: [entry, ...state.executionLog].slice(0, 200),
    }));
  },

  clearLog: () => {
    set({ executionLog: [] });
  },

  setRunning: (running) => {
    set({ isRunning: running });
  },
}));
