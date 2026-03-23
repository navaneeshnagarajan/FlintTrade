/**
 * FlowsSection — Flow Builder tab.
 * Shows node-type stats and the registered webhook list (create / delete).
 */

import { useState, useCallback } from "react";
import { Plus, Trash2, Loader2 } from "lucide-react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import { GlassCard } from "@/components/ui/GlassCard";
import { StaggeredList } from "@/components/motion/StaggeredList";
import {
  getWebhooks,
  createWebhook,
  deleteWebhook,
  type WebhookConfig,
} from "@/services/ftApi";
import { InlineToast } from "./shared";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type WebhookFormState = {
  name: string;
  type: "tradingview" | "chartink" | "custom";
  path: string;
  secret: string;
  enabled: boolean;
};

const EMPTY_WEBHOOK_FORM: WebhookFormState = {
  name: "",
  type: "tradingview",
  path: "",
  secret: "",
  enabled: true,
};

const WEBHOOK_TYPE_LABELS: Record<WebhookConfig["type"], string> = {
  tradingview: "TradingView",
  chartink:    "ChartInk",
  custom:      "Custom",
};

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function FlowsSection() {
  const queryClient = useQueryClient();
  const [showForm, setShowForm] = useState(false);
  const [form, setForm]         = useState<WebhookFormState>(EMPTY_WEBHOOK_FORM);
  const [toast, setToast]       = useState<{ msg: string; variant: "success" | "error" } | null>(null);
  const dismissToast            = useCallback(() => setToast(null), []);

  const { data: webhooksData, isLoading: loadingWebhooks, isError: webhooksError } = useQuery({
    queryKey: ["webhooks"],
    queryFn: getWebhooks,
  });

  const webhooks: WebhookConfig[] = webhooksData?.webhooks ?? [];

  const createMutation = useMutation({
    mutationFn: (cfg: Omit<WebhookConfig, "id">) => createWebhook(cfg),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["webhooks"] });
      setForm(EMPTY_WEBHOOK_FORM);
      setShowForm(false);
      setToast({ msg: "Webhook created", variant: "success" });
    },
    onError: (err: Error) => {
      setToast({ msg: err.message ?? "Failed to create webhook", variant: "error" });
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => deleteWebhook(id),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["webhooks"] });
      setToast({ msg: "Webhook deleted", variant: "success" });
    },
    onError: (err: Error) => {
      setToast({ msg: err.message ?? "Failed to delete webhook", variant: "error" });
    },
  });

  const handleCreate = () => {
    if (!form.name.trim() || !form.path.trim()) return;
    createMutation.mutate(form);
  };

  return (
    <div className="space-y-4">
      <StaggeredList className="space-y-4">

        {/* Overview */}
        <GlassCard className="p-6">
          <h3 className="font-heading font-semibold text-lg text-text-primary mb-2">Flow Builder</h3>
          <p className="text-sm text-text-secondary leading-relaxed mb-4">
            Build trading automations visually with a 54-node drag-and-drop flow builder.
            Connect market data triggers, conditions, and order actions without writing code.
            Flows run server-side and persist across sessions.
          </p>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
            <div className="bg-surface-base border border-border-default rounded-lg p-4">
              <p className="text-xs text-text-muted mb-1">Node Types</p>
              <p className="text-2xl font-mono font-bold text-text-primary">54</p>
            </div>
            <div className="bg-surface-base border border-border-default rounded-lg p-4">
              <p className="text-xs text-text-muted mb-1">Categories</p>
              <p className="text-2xl font-mono font-bold text-text-primary">8</p>
            </div>
            <div className="bg-surface-base border border-border-default rounded-lg p-4">
              <p className="text-xs text-text-muted mb-1">Execution</p>
              <p className="text-2xl font-mono font-bold text-accent">Server-side</p>
            </div>
          </div>
        </GlassCard>

        {/* Node categories */}
        <GlassCard className="p-6">
          <h3 className="font-heading font-semibold text-sm text-text-primary mb-2">Node Categories</h3>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
            {["Triggers", "Conditions", "Actions", "Orders", "Indicators", "Data", "Alerts", "Utilities"].map((cat) => (
              <div key={cat} className="bg-surface-base border border-border-default rounded-lg p-3 text-center">
                <p className="text-xs font-semibold text-text-primary">{cat}</p>
              </div>
            ))}
          </div>
        </GlassCard>

        {/* Webhooks */}
        <GlassCard className="p-6">
          <div className="flex items-center justify-between mb-4">
            <div>
              <h3 className="font-heading font-semibold text-sm text-text-primary">Registered Webhooks</h3>
              <p className="text-xs text-text-muted mt-0.5">
                Inbound webhook endpoints for TradingView, ChartInk, and custom alert sources.
              </p>
            </div>
            <Button
              size="sm"
              variant="outline"
              onClick={() => setShowForm((v) => !v)}
              className="h-7 px-3 gap-1.5 border-border-default text-text-primary hover:text-accent hover:border-accent text-xs"
            >
              <Plus size={12} />
              {showForm ? "Cancel" : "Create Webhook"}
            </Button>
          </div>

          {/* Create form */}
          {showForm && (
            <div className="bg-surface-base border border-border-default rounded-lg p-4 mb-4 space-y-3">
              <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                <div className="space-y-1">
                  <label className="text-xs text-text-muted">Name</label>
                  <Input
                    value={form.name}
                    onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
                    placeholder="My TradingView alert"
                    className="h-8 text-xs bg-surface-card border-border-default text-text-primary"
                  />
                </div>
                <div className="space-y-1">
                  <label className="text-xs text-text-muted">Type</label>
                  <select
                    value={form.type}
                    onChange={(e) => setForm((f) => ({ ...f, type: e.target.value as WebhookFormState["type"] }))}
                    className="w-full h-8 rounded-md border border-border-default bg-surface-card text-text-primary text-xs px-2 focus:outline-none focus:ring-1 focus:ring-accent"
                  >
                    <option value="tradingview">TradingView</option>
                    <option value="chartink">ChartInk</option>
                    <option value="custom">Custom</option>
                  </select>
                </div>
                <div className="space-y-1">
                  <label className="text-xs text-text-muted">Path (e.g. /webhook/my-alert)</label>
                  <Input
                    value={form.path}
                    onChange={(e) => setForm((f) => ({ ...f, path: e.target.value }))}
                    placeholder="/webhook/nifty-breakout"
                    className="h-8 text-xs bg-surface-card border-border-default text-text-primary"
                  />
                </div>
                <div className="space-y-1">
                  <label className="text-xs text-text-muted">Secret (optional)</label>
                  <Input
                    value={form.secret}
                    onChange={(e) => setForm((f) => ({ ...f, secret: e.target.value }))}
                    placeholder="Optional HMAC secret"
                    type="password"
                    className="h-8 text-xs bg-surface-card border-border-default text-text-primary"
                  />
                </div>
              </div>
              <div className="flex justify-end">
                <Button
                  size="sm"
                  onClick={handleCreate}
                  disabled={createMutation.isPending || !form.name.trim() || !form.path.trim()}
                  className="h-7 px-4 text-xs gap-1.5"
                >
                  {createMutation.isPending ? <Loader2 size={12} className="animate-spin" /> : <Plus size={12} />}
                  Create
                </Button>
              </div>
            </div>
          )}

          {toast && (
            <div className="mb-3">
              <InlineToast message={toast.msg} variant={toast.variant} onDismiss={dismissToast} />
            </div>
          )}

          {loadingWebhooks && (
            <div className="flex items-center justify-center py-8">
              <Loader2 size={18} className="animate-spin text-text-muted" />
            </div>
          )}

          {webhooksError && (
            <p className="text-xs text-loss text-center py-4">
              Failed to load webhooks. Backend may be offline.
            </p>
          )}

          {!loadingWebhooks && !webhooksError && webhooks.length === 0 && (
            <p className="text-xs text-text-muted text-center py-6">
              No webhooks registered. Create one above to start receiving alerts.
            </p>
          )}

          {!loadingWebhooks && webhooks.length > 0 && (
            <Table>
              <TableHeader>
                <TableRow className="border-border-default hover:bg-transparent">
                  <TableHead className="text-xs text-text-muted font-medium">Name</TableHead>
                  <TableHead className="text-xs text-text-muted font-medium">Type</TableHead>
                  <TableHead className="text-xs text-text-muted font-medium">Path</TableHead>
                  <TableHead className="text-xs text-text-muted font-medium">Status</TableHead>
                  <TableHead className="text-xs text-text-muted font-medium w-10" />
                </TableRow>
              </TableHeader>
              <TableBody>
                {webhooks.map((wh) => (
                  <TableRow key={wh.id} className="border-border-default hover:bg-surface-base">
                    <TableCell className="text-xs text-text-primary font-medium py-2">{wh.name}</TableCell>
                    <TableCell className="py-2">
                      <Badge className="text-xs bg-accent/10 text-accent border-0">
                        {WEBHOOK_TYPE_LABELS[wh.type]}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-xs font-mono text-text-secondary py-2">{wh.path}</TableCell>
                    <TableCell className="py-2">
                      {wh.enabled ? (
                        <Badge className="text-xs bg-profit/10 text-profit border-0">Active</Badge>
                      ) : (
                        <Badge className="text-xs bg-text-muted/10 text-text-muted border-0">Disabled</Badge>
                      )}
                    </TableCell>
                    <TableCell className="py-2">
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() => deleteMutation.mutate(wh.id)}
                        disabled={deleteMutation.isPending}
                        className="h-6 w-6 p-0 text-text-muted hover:text-loss"
                      >
                        <Trash2 size={12} />
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </GlassCard>

      </StaggeredList>
    </div>
  );
}
