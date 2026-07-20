/**
 * FlowCanvas — React Flow canvas editor for a single flow.
 *
 * Saving PUTs the workflow to the backend flow store (upsert) and refreshes
 * the ["flows"] list query; the toolbar label only claims "saved" after the
 * backend confirmed the write.
 */

import "@xyflow/react/dist/style.css";

import React, { useState, useCallback, type DragEvent } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  ReactFlow,
  Background,
  BackgroundVariant,
  Controls,
  MiniMap,
  Panel,
} from "@xyflow/react";
import { Workflow, Save, Trash2, ChevronRight } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

import { putFlow } from "@/services/ftApi.flows";
import { useFlowStore } from "@/stores/flowStore";
import { NodePalette, DRAG_MIME } from "./NodePalette";
import { ConfigPanel } from "./ConfigPanel";
import { ExecutionLog } from "./ExecutionLog";
import { REACT_FLOW_NODE_TYPES } from "./BaseNode";
import {
  NODE_TYPE_TO_CATEGORY,
  NODE_TYPE_TO_COLOR,
  NODE_TYPE_TO_LABEL,
} from "./nodeRegistry";
import type { FlowNodeData } from "@/stores/flowStore";
import type { Node } from "@xyflow/react";

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

export interface FlowCanvasProps {
  flowId: string;
  flowName: string;
  onBack: () => void;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function FlowCanvas({ flowId, flowName, onBack }: FlowCanvasProps) {
  const nodes = useFlowStore((s) => s.nodes);
  const edges = useFlowStore((s) => s.edges);
  const selectedNodeId = useFlowStore((s) => s.selectedNodeId);
  const onNodesChange = useFlowStore((s) => s.onNodesChange);
  const onEdgesChange = useFlowStore((s) => s.onEdgesChange);
  const onConnect = useFlowStore((s) => s.onConnect);
  const addNode = useFlowStore((s) => s.addNode);
  const selectNode = useFlowStore((s) => s.selectNode);
  const clearCanvas = useFlowStore((s) => s.clearCanvas);
  const addLogEntry = useFlowStore((s) => s.addLogEntry);

  const queryClient = useQueryClient();
  const [name, setName] = useState(flowName);
  const [saved, setSaved] = useState(true);
  const [logCollapsed, setLogCollapsed] = useState(false);

  const saveMutation = useMutation({
    mutationFn: putFlow,
    onSuccess: (result, flow) => {
      setSaved(true);
      addLogEntry(
        "success",
        `Workflow "${flow.name}" saved to your workspace (${flow.nodes.length} nodes, ${flow.edges.length} edges)`
      );
      const warnings = Array.isArray(result.validation) ? result.validation.length : 0;
      if (warnings > 0) {
        addLogEntry(
          "warning",
          `Backend reported ${warnings} validation issue${warnings === 1 ? "" : "s"} for this flow`
        );
      }
      void queryClient.invalidateQueries({ queryKey: ["flows"] });
    },
    onError: (error: Error, flow) => {
      addLogEntry("error", `Could not save "${flow.name}" to the workspace: ${error.message}`);
    },
  });

  const selectedNode = nodes.find((n) => n.id === selectedNodeId) ?? null;

  const addNodeAt = useCallback(
    (nodeType: string, position: { x: number; y: number }) => {
      const catId = NODE_TYPE_TO_CATEGORY.get(nodeType) ?? "utilities";
      const color = NODE_TYPE_TO_COLOR.get(nodeType) ?? "#a78bfa";
      const label = NODE_TYPE_TO_LABEL.get(nodeType) ?? nodeType;

      addNode(nodeType, position, label, catId, color);
      setSaved(false);
    },
    [addNode]
  );

  const handleDrop = useCallback(
    (e: DragEvent<HTMLDivElement>) => {
      e.preventDefault();
      const nodeType = e.dataTransfer.getData(DRAG_MIME);
      if (!nodeType) return;

      const bounds = (e.currentTarget as HTMLDivElement).getBoundingClientRect();
      const position = {
        x: e.clientX - bounds.left,
        y: e.clientY - bounds.top,
      };

      addNodeAt(nodeType, position);
    },
    [addNodeAt]
  );

  const handlePaletteAdd = useCallback(
    (nodeType: string) => {
      const index = nodes.length;
      addNodeAt(nodeType, {
        x: 120 + (index % 4) * 180,
        y: 80 + Math.floor(index / 4) * 120,
      });
    },
    [addNodeAt, nodes.length]
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
    saveMutation.mutate({
      id: flowId,
      name,
      nodes,
      edges,
      updatedAt: new Date().toISOString(),
    });
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
          <Button
            size="icon"
            variant="ghost"
            className="h-6 w-6 text-text-muted hover:text-text-primary"
            onClick={onBack}
            aria-label="Back to flow list"
          >
            <ChevronRight size={14} className="rotate-180" />
          </Button>
          <Input
            aria-label="Flow name"
            value={name}
            onChange={(e) => { setName(e.target.value); setSaved(false); }}
            className="h-6 w-44 px-1.5 text-xs font-semibold bg-transparent border-transparent hover:border-border-default focus-visible:border-border-default rounded"
          />
          {saveMutation.isPending ? (
            <span style={{ fontSize: 10, color: "var(--color-text-muted)" }}>Saving…</span>
          ) : saveMutation.isError && !saved ? (
            <span style={{ fontSize: 10, color: "var(--color-bearish, #f87171)" }}>
              Not saved — {saveMutation.error.message}
            </span>
          ) : !saved ? (
            <span style={{ fontSize: 10, color: "var(--color-text-muted)" }}>Unsaved</span>
          ) : null}
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
            className="h-6 px-3 bg-primary hover:bg-primary/90 text-white text-xs gap-1"
            onClick={handleSave}
            disabled={saved || saveMutation.isPending}
          >
            <Save size={11} />
            {saveMutation.isPending ? "Saving…" : "Save"}
          </Button>
        </div>
      </div>

      {/* Canvas row: palette + React Flow + config panel */}
      <div style={{ flex: 1, display: "flex", minHeight: 0 }}>
        {/* Left: Node palette */}
        <NodePalette onAddNode={handlePaletteAdd} />

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
            <Background
              variant={BackgroundVariant.Dots}
              gap={16}
              size={0.6}
              color="var(--color-border)"
            />

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
                    Choose or drag a node from the palette
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
