/**
 * N8nSection — n8n Bridge tab.
 *
 * Surfaces the n8n workflow-automation bridge (an OPTIONAL external
 * self-hosted service, like OpenAlgo/OpenClaw): connection health, the
 * workflow list with activate/deactivate controls, and a manual webhook
 * trigger. Honest states throughout — offline shows a setup hint, a missing
 * N8N_API_KEY shows the backend's real error, nothing is fabricated.
 *
 *   GET  /api/v1/automation/n8n/health
 *   GET  /api/v1/automation/n8n/workflows
 *   POST /api/v1/automation/n8n/workflows/<id>/(de)activate
 *   POST /api/v1/automation/n8n/webhook/trigger
 */

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, Power, RefreshCw, Send, Workflow as WorkflowIcon } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { GlassCard } from "@/components/ui/GlassCard";
import {
  activateN8nWorkflow,
  checkN8nHealth,
  deactivateN8nWorkflow,
  listN8nWorkflows,
  triggerN8nWebhook,
  type N8nWorkflow,
} from "@/services/ftApi";

export default function N8nSection() {
  const queryClient = useQueryClient();
  const [pendingWorkflow, setPendingWorkflow] = useState<string | null>(null);
  const [webhookId, setWebhookId] = useState("");
  const [triggerResult, setTriggerResult] = useState<string | null>(null);

  // 503 (offline) rejects the promise → isError doubles as "offline".
  const healthQuery = useQuery({
    queryKey: ["n8n", "health"],
    queryFn: checkN8nHealth,
    retry: false,
    refetchInterval: 30_000,
  });
  const online = healthQuery.data?.running === true;

  const workflowsQuery = useQuery({
    queryKey: ["n8n", "workflows"],
    queryFn: listN8nWorkflows,
    enabled: online,
    retry: false,
  });

  const toggleMutation = useMutation({
    mutationFn: ({ id, active }: { id: string; active: boolean }): Promise<{ workflow_id: string; active: boolean }> =>
      active ? deactivateN8nWorkflow(id) : activateN8nWorkflow(id),
    onMutate: ({ id }) => setPendingWorkflow(id),
    onSettled: () => {
      setPendingWorkflow(null);
      void queryClient.invalidateQueries({ queryKey: ["n8n", "workflows"] });
    },
  });

  const triggerMutation = useMutation({
    mutationFn: (id: string) => triggerN8nWebhook(id),
    onSuccess: () => setTriggerResult("Webhook triggered — check the workflow's execution log in n8n."),
    onError: (err: Error) => setTriggerResult(err.message),
  });

  const workflows: N8nWorkflow[] = workflowsQuery.data?.workflows ?? [];

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-2">
        <div>
          <h2 className="text-sm font-semibold text-text-primary flex items-center gap-2">
            <WorkflowIcon size={15} className="text-accent" aria-hidden="true" />
            n8n Bridge
          </h2>
          <p className="text-xs text-text-muted mt-0.5">
            Optional external workflow automation — trigger n8n workflows from FlintTrade
            and manage their activation.
          </p>
        </div>
        <span
          className={
            online
              ? "text-xxs px-2 py-0.5 rounded-full border border-profit/30 bg-profit/10 text-profit"
              : "text-xxs px-2 py-0.5 rounded-full border border-border-subtle bg-text-muted/10 text-text-muted"
          }
        >
          {healthQuery.isLoading ? "Checking…" : online ? "Online" : "Offline"}
        </span>
      </div>

      {!healthQuery.isLoading && !online && (
        <GlassCard className="p-4 space-y-2">
          <p className="text-xs text-text-secondary">
            No n8n instance is reachable. n8n is a self-hosted automation tool — to use
            the bridge, run one (default <code className="font-mono">http://127.0.0.1:5678</code>)
            and set <code className="font-mono">N8N_HOST</code> in the backend environment.
            Workflow management additionally needs <code className="font-mono">N8N_API_KEY</code>.
          </p>
          <Button
            size="sm"
            variant="outline"
            onClick={() => void healthQuery.refetch()}
            className="gap-1.5"
          >
            <RefreshCw size={13} /> Re-check
          </Button>
        </GlassCard>
      )}

      {online && (
        <>
          {/* Workflows */}
          <GlassCard className="p-4 space-y-3">
            <h3 className="text-xs font-semibold text-text-primary">Workflows</h3>
            {workflowsQuery.isLoading ? (
              <p className="text-xs text-text-muted">Loading workflows…</p>
            ) : workflowsQuery.isError ? (
              <p role="alert" className="text-xs text-warning">
                {workflowsQuery.error instanceof Error
                  ? workflowsQuery.error.message
                  : "Could not list workflows."}{" "}
                Listing and activation need an n8n API key — set{" "}
                <code className="font-mono">N8N_API_KEY</code> in the backend environment.
              </p>
            ) : workflows.length === 0 ? (
              <p className="text-xs text-text-muted">
                No workflows in this n8n instance yet — create one in the n8n editor.
              </p>
            ) : (
              <ul className="divide-y divide-border-subtle" aria-label="n8n workflows">
                {workflows.map((wf) => (
                  <li key={wf.id} className="flex items-center justify-between gap-2 py-2">
                    <span className="text-xs text-text-primary">
                      {wf.name}
                      <span className={wf.active ? "ml-2 text-xxs text-profit" : "ml-2 text-xxs text-text-muted"}>
                        {wf.active ? "Active" : "Inactive"}
                      </span>
                    </span>
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() => toggleMutation.mutate({ id: wf.id, active: wf.active })}
                      disabled={pendingWorkflow === wf.id}
                      aria-label={`${wf.active ? "Deactivate" : "Activate"} workflow ${wf.name}`}
                      className="gap-1.5 h-6 text-xxs"
                    >
                      {pendingWorkflow === wf.id ? (
                        <Loader2 size={12} className="animate-spin" />
                      ) : (
                        <Power size={12} />
                      )}
                      {wf.active ? "Deactivate" : "Activate"}
                    </Button>
                  </li>
                ))}
              </ul>
            )}
          </GlassCard>

          {/* Manual webhook trigger */}
          <GlassCard className="p-4 space-y-3">
            <h3 className="text-xs font-semibold text-text-primary">Trigger a webhook workflow</h3>
            <p className="text-xs text-text-muted">
              Fires the n8n webhook with the given ID (the UUID from the workflow's
              Webhook node). No API key needed — the webhook ID is the secret.
            </p>
            <form
              className="flex items-center gap-2"
              onSubmit={(e) => {
                e.preventDefault();
                const id = webhookId.trim();
                if (id) triggerMutation.mutate(id);
              }}
            >
              <Input
                value={webhookId}
                onChange={(e) => setWebhookId(e.target.value)}
                placeholder="Webhook ID"
                aria-label="n8n webhook ID"
                className="h-7 w-64 text-xs font-mono"
              />
              <Button
                type="submit"
                size="sm"
                variant="outline"
                disabled={triggerMutation.isPending || !webhookId.trim()}
                className="gap-1.5"
              >
                {triggerMutation.isPending ? (
                  <Loader2 size={13} className="animate-spin" />
                ) : (
                  <Send size={13} />
                )}
                Trigger
              </Button>
            </form>
            {triggerResult && (
              <p
                role="status"
                className={triggerMutation.isError ? "text-xs text-loss" : "text-xs text-profit"}
              >
                {triggerResult}
              </p>
            )}
          </GlassCard>
        </>
      )}
    </div>
  );
}
