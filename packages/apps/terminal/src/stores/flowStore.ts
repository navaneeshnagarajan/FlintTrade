/**
 * flowStore.ts — Zustand store for the Flow Builder tool.
 *
 * Canvas/UI state ONLY: React Flow nodes/edges being edited, selection,
 * execution log, and the id of the flow currently open in the editor.
 * Saved workflows persist on the FlintTrade backend via
 * :mod:`services/ftApi.flows` (TanStack Query owns that server state) — this
 * store no longer reads or writes localStorage.
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

/**
 * A saved workflow document — the shape stored verbatim by the backend flow
 * store (``PUT /api/v1/flows/<id>``) and used by templates/canvas loading.
 */
export interface SavedWorkflow {
  id: string;
  name: string;
  nodes: Node<FlowNodeData>[];
  edges: Edge[];
  updatedAt: string;
}

interface FlowState {
  // React Flow state
  nodes: Node<FlowNodeData>[];
  edges: Edge[];
  selectedNodeId: string | null;
  isRunning: boolean;
  executionLog: LogEntry[];

  /** Id of the flow currently open in the editor (null = none). */
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
  setActiveFlowId: (id: string | null) => void;

  // Execution log
  addLogEntry: (level: LogLevel, message: string) => void;
  clearLog: () => void;
  setRunning: (running: boolean) => void;
}

let logCounter = 1;
function genLogId(): string {
  return `log_${logCounter++}`;
}

// ---------------------------------------------------------------------------
// Store
// ---------------------------------------------------------------------------

export const useFlowStore = create<FlowState>((set) => ({
  nodes: [],
  edges: [],
  selectedNodeId: null,
  isRunning: false,
  executionLog: [],
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

  setActiveFlowId: (id) => {
    set({ activeFlowId: id });
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
