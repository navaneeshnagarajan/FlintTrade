/**
 * FlowsTab — list view of saved flows within FlowBuilderTool.
 */

import { CheckCircle2, Play, XCircle, Pause, Workflow, Plus, FolderOpen, Trash2, Package } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { useFlowStore } from "@/stores/flowStore";
import { getTotalNodeCount } from "./nodeRegistry";

// ---------------------------------------------------------------------------
// StatusIcon
// ---------------------------------------------------------------------------

export type FlowStatus = "active" | "inactive" | "running" | "error";

export function StatusIcon({ status }: { status: FlowStatus }) {
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

// ---------------------------------------------------------------------------
// FlowsTab
// ---------------------------------------------------------------------------

export interface FlowsTabProps {
  onNew: () => void;
  onOpen: (id: string) => void;
  onFromTemplate: () => void;
}

export function FlowsTab({ onNew, onOpen, onFromTemplate }: FlowsTabProps) {
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
