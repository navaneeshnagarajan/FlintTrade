/**
 * FlowBuilderTool — Visual workflow automation builder
 *
 * Canvas powered by @xyflow/react v12 (React Flow).
 * Layout:
 *   - Left: NodePalette (categorised + searchable draggable nodes)
 *   - Centre: React Flow canvas with custom BaseNode
 *   - Right: ConfigPanel (shown when a node is selected)
 *   - Bottom: ExecutionLog (collapsible)
 *   - Top: Toolbar (Save, Clear, New Flow, back navigation)
 *
 * Canvas/UI state lives in flowStore (Zustand). Saved workflows persist on
 * the FlintTrade backend via ftApi.flows (TanStack Query); legacy
 * localStorage drafts are imported once on mount.
 *
 * Node catalogue across 8 categories:
 *   Triggers · Orders · Conditions · Logic · Data · WebSocket · Account · Integration
 *
 * Modules:
 *   flow/FlowTemplates.ts     — template data + workflow factories
 *   flow/FlowCanvas.tsx       — React Flow canvas editor
 *   flow/FlowsTab.tsx         — saved flows list + StatusIcon
 *   flow/TemplatesTab.tsx     — template browser + DifficultyBadge
 *   flow/HowItWorksTab.tsx    — reference guide
 *   flow/legacyFlowImport.ts  — one-time localStorage → backend migration
 */

import { useEffect, useRef, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { X, Workflow, AlertTriangle } from "lucide-react";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";

import { useFlowStore } from "@/stores/flowStore";
import { useModeStore } from "@/stores/modeStore";
import { getFlow, putFlow } from "@/services/ftApi.flows";
import { FlowCanvas } from "./flow/FlowCanvas";
import { FlowsTab } from "./flow/FlowsTab";
import { TemplatesTab } from "./flow/TemplatesTab";
import { HowItWorksTab } from "./flow/HowItWorksTab";
import { getTotalNodeCount } from "./flow/nodeRegistry";
import { importLegacyFlows } from "./flow/legacyFlowImport";
import { FLOW_TEMPLATES, type FlowTemplate } from "./flow/FlowTemplates";
import type { FlowNodeData, SavedWorkflow } from "@/stores/flowStore";
import type { Node } from "@xyflow/react";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface Props {
  onClose?: () => void;
}

type View = "list" | "editor";

// ---------------------------------------------------------------------------
// Main export
// ---------------------------------------------------------------------------

export default function FlowBuilderTool({ onClose }: Props) {
  const [view, setView] = useState<View>("list");
  const [activeFlowName, setActiveFlowName] = useState("Untitled Flow");
  const [activeTab, setActiveTab] = useState("flows");
  const [openError, setOpenError] = useState<string | null>(null);

  const queryClient = useQueryClient();
  const activeFlowId = useFlowStore((s) => s.activeFlowId);
  const loadWorkflowIntoCanvas = useFlowStore((s) => s.loadWorkflowIntoCanvas);
  const addLogEntry = useFlowStore((s) => s.addLogEntry);

  // One-time migration of legacy localStorage drafts into the backend store.
  // Skipped in Explore mode (no real backend session to import into); the
  // localStorage key survives until an eligible session completes the import.
  const importAttempted = useRef(false);
  useEffect(() => {
    if (importAttempted.current) return;
    importAttempted.current = true;
    if (useModeStore.getState().mode === "explore") return;
    void importLegacyFlows()
      .then((count) => {
        if (count > 0) {
          addLogEntry(
            "info",
            `Imported ${count} draft flow${count === 1 ? "" : "s"} from this browser into your workspace`
          );
          void queryClient.invalidateQueries({ queryKey: ["flows"] });
        }
      })
      .catch(() => {
        // Import failed wholesale — the localStorage key is kept, so the
        // next mount retries. Nothing user-visible to do here.
      });
  }, [queryClient, addLogEntry]);

  const saveMutation = useMutation({
    mutationFn: putFlow,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["flows"] });
    },
    onError: (error: Error, flow) => {
      addLogEntry("error", `Could not save "${flow.name}" to the workspace: ${error.message}`);
    },
  });

  function handleNewFlow(): void {
    const id = `flow_${Date.now()}`;
    const workflow: SavedWorkflow = {
      id,
      name: "New Flow",
      nodes: [],
      edges: [],
      updatedAt: new Date().toISOString(),
    };
    loadWorkflowIntoCanvas(workflow);
    setActiveFlowName(workflow.name);
    setOpenError(null);
    setView("editor");
    saveMutation.mutate(workflow);
  }

  function handleOpenFlow(id: string): void {
    setOpenError(null);
    queryClient
      .fetchQuery({ queryKey: ["flows", id], queryFn: () => getFlow(id) })
      .then((flow) => {
        loadWorkflowIntoCanvas(flow);
        setActiveFlowName(flow.name);
        setView("editor");
      })
      .catch((error: unknown) => {
        setOpenError(
          `Could not open the flow: ${error instanceof Error ? error.message : String(error)}`
        );
      });
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

    loadWorkflowIntoCanvas(workflow);
    setActiveFlowName(workflow.name);
    setOpenError(null);
    setView("editor");
    saveMutation.mutate(workflow);
  }

  // Editor view — full page canvas
  if (view === "editor" && activeFlowId) {
    return (
      <div className="h-full flex flex-col bg-surface-base">
        <FlowCanvas
          flowId={activeFlowId}
          flowName={activeFlowName}
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
          <Button variant="ghost" size="icon" onClick={onClose} className="h-6 w-6 text-text-muted hover:text-text-primary" aria-label="Close Flow Builder">
            <X size={15} />
          </Button>
        )}
      </div>

      {openError && (
        <div className="mx-4 mt-3 flex items-start gap-2 rounded-md border border-atm-border bg-atm-bg px-3 py-2 text-xs text-text-secondary">
          <AlertTriangle size={13} className="mt-0.5 shrink-0 text-amber-400" />
          <span>{openError}</span>
        </div>
      )}

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

// Re-export for consumers that import from this barrel
export { FLOW_TEMPLATES };
export type { FlowTemplate };
