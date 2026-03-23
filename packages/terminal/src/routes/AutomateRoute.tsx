import React, { useState, useEffect, useCallback } from "react";
import {
  Workflow,
  Clock,
  Activity,
  FileText,
  Settings2,
  Loader2,
  CheckCircle2,
  Send,
  Pause,
  Play,
  Square,
  Trash2,
  Plus,
  ShieldAlert,
  ShieldCheck,
  AlertTriangle,
  RefreshCw,
} from "lucide-react";
import { motion } from "framer-motion";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { GlassCard } from "@/components/ui/GlassCard";
import TabTransition from "@/components/motion/TabTransition";
import { StaggeredList } from "@/components/motion/StaggeredList";
import { sendTelegram } from "@/services/api";
import {
  getCronJobs,
  pauseCronJob,
  resumeCronJob,
  getRunningStrategies,
  stopStrategy,
  getAuditLogs,
  getSafetyConfig,
  updateSafetyConfig,
  activateKillSwitch,
  resetKillSwitch,
  getWebhooks,
  createWebhook,
  deleteWebhook,
  type CronJob,
  type RunningStrategy,
  type AuditLog,
  type SafetyConfig,
  type WebhookConfig,
} from "@/services/ftApi";

// ---------------------------------------------------------------------------
// CSS keyframe styles injected once at module load
// ---------------------------------------------------------------------------

const PULSE_STYLES = `
@keyframes ft-pulse-green {
  0%, 100% { opacity: 1; box-shadow: 0 0 0 0 rgba(34,197,94,0.4); }
  50%       { opacity: 0.7; box-shadow: 0 0 0 4px rgba(34,197,94,0); }
}
@keyframes ft-pulse-red {
  0%, 100% { opacity: 1; box-shadow: 0 0 0 0 rgba(239,68,68,0.5); }
  50%       { opacity: 0.6; box-shadow: 0 0 0 5px rgba(239,68,68,0); }
}
.ft-dot-running {
  width: 7px; height: 7px; border-radius: 50%;
  background: #22c55e;
  animation: ft-pulse-green 1.6s ease-in-out infinite;
  flex-shrink: 0;
}
.ft-dot-paused {
  width: 7px; height: 7px; border-radius: 50%;
  background: #f59e0b;
  flex-shrink: 0;
}
.ft-dot-kill {
  width: 7px; height: 7px; border-radius: 50%;
  background: #ef4444;
  animation: ft-pulse-red 1s ease-in-out infinite;
  flex-shrink: 0;
}
`;

// Inject once
if (typeof document !== "undefined") {
  const styleId = "ft-automate-pulse";
  if (!document.getElementById(styleId)) {
    const el = document.createElement("style");
    el.id = styleId;
    el.textContent = PULSE_STYLES;
    document.head.appendChild(el);
  }
}

// ---------------------------------------------------------------------------
// Section registry
// ---------------------------------------------------------------------------

type SectionId = "flows" | "schedules" | "monitors" | "logs" | "settings";

interface SectionDef {
  id: SectionId;
  label: string;
  icon: typeof Workflow;
  desc: string;
}

const SECTIONS: SectionDef[] = [
  { id: "flows",     label: "Flow Builder",         icon: Workflow,   desc: "Visual 54-node automation builder" },
  { id: "schedules", label: "Schedules",             icon: Clock,      desc: "Cron jobs & timed executions" },
  { id: "monitors",  label: "Monitors",              icon: Activity,   desc: "Live strategy monitoring" },
  { id: "logs",      label: "Execution Logs",        icon: FileText,   desc: "History of automated actions" },
  { id: "settings",  label: "Automation Settings",   icon: Settings2,  desc: "Kill switches, limits, Telegram alerts" },
];

// ---------------------------------------------------------------------------
// Icon rail — 48px collapsed, ~168px expanded on hover
// ---------------------------------------------------------------------------

interface IconRailProps {
  activeSection: SectionId;
  onSelect: (id: SectionId) => void;
  killSwitchActive: boolean;
  runningCount: number;
}

function IconRail({ activeSection, onSelect, killSwitchActive, runningCount }: IconRailProps) {
  const [expanded, setExpanded] = useState(false);

  return (
    <motion.nav
      aria-label="Section navigation"
      onHoverStart={() => setExpanded(true)}
      onHoverEnd={() => setExpanded(false)}
      animate={{ width: expanded ? 168 : 48 }}
      transition={{ duration: 0.2, ease: [0.25, 1, 0.5, 1] }}
      className="relative shrink-0 border-r border-border-default bg-surface-card overflow-hidden py-2 flex flex-col gap-0.5"
      style={{ minWidth: 48 }}
    >
      {SECTIONS.map((section) => {
        const Icon = section.icon;
        const isActive = activeSection === section.id;

        // Compute status dot for this rail item
        const dotClass =
          section.id === "settings" && killSwitchActive
            ? "ft-dot-kill"
            : section.id === "monitors" && runningCount > 0
            ? "ft-dot-running"
            : section.id === "schedules" && !killSwitchActive
            ? "ft-dot-paused"
            : null;

        return (
          <button
            key={section.id}
            role="tab"
            aria-selected={isActive}
            onClick={() => onSelect(section.id)}
            aria-current={isActive ? "true" : undefined}
            title={expanded ? undefined : section.label}
            className={`
              relative flex items-center gap-2.5 h-10 px-3 text-sm font-sans
              transition-colors duration-150 border-l-2 overflow-hidden
              ${
                isActive
                  ? "text-accent bg-accent/10 border-accent"
                  : "text-text-secondary hover:text-text-primary hover:bg-surface-base border-transparent"
              }
            `}
          >
            {/* Fixed icon position so rail doesn't jump */}
            <span className="shrink-0 flex items-center justify-center w-4 h-4 relative">
              <Icon size={16} />
              {dotClass && (
                <span
                  className={dotClass}
                  style={{ position: "absolute", top: -3, right: -3 }}
                />
              )}
            </span>

            {/* Label — fades in as rail expands */}
            <motion.span
              animate={{ opacity: expanded ? 1 : 0 }}
              transition={{ duration: 0.12, ease: "easeOut" }}
              className="whitespace-nowrap text-xs font-medium leading-none"
            >
              {section.label}
            </motion.span>
          </button>
        );
      })}
    </motion.nav>
  );
}

// ---------------------------------------------------------------------------
// Inline toast (no external toast library)
// ---------------------------------------------------------------------------

interface InlineToastProps {
  message: string;
  variant?: "success" | "error";
  onDismiss: () => void;
}

function InlineToast({ message, variant = "success", onDismiss }: InlineToastProps) {
  useEffect(() => {
    const id = setTimeout(onDismiss, 3000);
    return () => clearTimeout(id);
  }, [onDismiss]);

  const cls =
    variant === "error"
      ? "bg-loss/10 border-loss/20 text-loss"
      : "bg-profit/10 border-profit/20 text-profit";

  return (
    <div className={`flex items-center gap-2 px-3 py-2 rounded text-xs border ${cls}`}>
      <CheckCircle2 size={13} className="flex-none" />
      <span>{message}</span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Section 1: Flows — with real webhook list
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

function FlowsSection() {
  const queryClient = useQueryClient();
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState<WebhookFormState>(EMPTY_WEBHOOK_FORM);
  const [toast, setToast] = useState<{ msg: string; variant: "success" | "error" } | null>(null);
  const dismissToast = useCallback(() => setToast(null), []);

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
        {/* Info cards */}
        <GlassCard className="p-6">
          <h3 className="font-heading font-semibold text-lg text-text-primary mb-2">
            Flow Builder
          </h3>
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

        <GlassCard className="p-6">
          <h3 className="font-heading font-semibold text-sm text-text-primary mb-2">
            Node Categories
          </h3>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
            {[
              "Triggers", "Conditions", "Actions", "Orders",
              "Indicators", "Data", "Alerts", "Utilities",
            ].map((cat) => (
              <div
                key={cat}
                className="bg-surface-base border border-border-default rounded-lg p-3 text-center"
              >
                <p className="text-xs font-semibold text-text-primary">{cat}</p>
              </div>
            ))}
          </div>
        </GlassCard>

        {/* Webhooks */}
        <GlassCard className="p-6">
          <div className="flex items-center justify-between mb-4">
            <div>
              <h3 className="font-heading font-semibold text-sm text-text-primary">
                Registered Webhooks
              </h3>
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
                    onChange={(e) =>
                      setForm((f) => ({
                        ...f,
                        type: e.target.value as WebhookFormState["type"],
                      }))
                    }
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
                  {createMutation.isPending ? (
                    <Loader2 size={12} className="animate-spin" />
                  ) : (
                    <Plus size={12} />
                  )}
                  Create
                </Button>
              </div>
            </div>
          )}

          {/* Toast */}
          {toast && (
            <div className="mb-3">
              <InlineToast message={toast.msg} variant={toast.variant} onDismiss={dismissToast} />
            </div>
          )}

          {/* Webhook list */}
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
                  <TableRow
                    key={wh.id}
                    className="border-border-default hover:bg-surface-base"
                  >
                    <TableCell className="text-xs text-text-primary font-medium py-2">
                      {wh.name}
                    </TableCell>
                    <TableCell className="py-2">
                      <Badge className="text-xs bg-accent/10 text-accent border-0">
                        {WEBHOOK_TYPE_LABELS[wh.type]}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-xs font-mono text-text-secondary py-2">
                      {wh.path}
                    </TableCell>
                    <TableCell className="py-2">
                      {wh.enabled ? (
                        <Badge className="text-xs bg-profit/10 text-profit border-0">Active</Badge>
                      ) : (
                        <Badge className="text-xs bg-text-muted/10 text-text-muted border-0">
                          Disabled
                        </Badge>
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

// ---------------------------------------------------------------------------
// Section 2: Schedules — live cron jobs
// ---------------------------------------------------------------------------

function StatusDot({ status }: { status: string }) {
  const lower = status.toLowerCase();
  if (lower === "active") return <span className="ft-dot-running" />;
  if (lower === "paused") return <span className="ft-dot-paused" />;
  if (lower === "error")  return <span className="ft-dot-kill" />;
  return <span className="ft-dot-paused" style={{ background: "#6b7280" }} />;
}

function StatusBadge({ status }: { status: string }) {
  const lower = status.toLowerCase();
  if (lower === "active") {
    return <Badge className="text-xs bg-profit/10 text-profit border-0">Active</Badge>;
  }
  if (lower === "paused") {
    return <Badge className="text-xs bg-atm-bg text-warning border-0">Paused</Badge>;
  }
  if (lower === "error") {
    return <Badge className="text-xs bg-loss/10 text-loss border-0">Error</Badge>;
  }
  return (
    <Badge className="text-xs bg-text-muted/10 text-text-muted border-0">{status}</Badge>
  );
}

function SchedulesSection() {
  const queryClient = useQueryClient();
  const [pendingJob, setPendingJob] = useState<string | null>(null);

  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ["cronJobs"],
    queryFn: getCronJobs,
  });

  const jobs: CronJob[] = data?.jobs ?? [];

  const pauseMutation = useMutation({
    mutationFn: (name: string) => pauseCronJob(name),
    onMutate: (name) => setPendingJob(name),
    onSettled: () => {
      setPendingJob(null);
      void queryClient.invalidateQueries({ queryKey: ["cronJobs"] });
    },
  });

  const resumeMutation = useMutation({
    mutationFn: (name: string) => resumeCronJob(name),
    onMutate: (name) => setPendingJob(name),
    onSettled: () => {
      setPendingJob(null);
      void queryClient.invalidateQueries({ queryKey: ["cronJobs"] });
    },
  });

  const toggleJob = (job: CronJob) => {
    if (job.status.toLowerCase() === "paused") {
      resumeMutation.mutate(job.name);
    } else {
      pauseMutation.mutate(job.name);
    }
  };

  const formatLastRun = (val: string | null) => {
    if (!val) return "Never";
    try {
      return new Date(val).toLocaleString("en-IN", {
        timeZone: "Asia/Kolkata",
        dateStyle: "short",
        timeStyle: "short",
      });
    } catch {
      return val;
    }
  };

  return (
    <div className="space-y-4">
      <GlassCard className="p-6">
        <div className="flex items-center justify-between mb-4">
          <div>
            <h3 className="font-heading font-semibold text-lg text-text-primary">
              Cron Scheduler
            </h3>
            <p className="text-sm text-text-secondary mt-0.5">
              All registered automation schedules. Pause or resume individual jobs.
            </p>
          </div>
          <Button
            size="sm"
            variant="ghost"
            onClick={() => void refetch()}
            disabled={isLoading}
            className="h-7 w-7 p-0 text-text-muted hover:text-text-primary"
          >
            <RefreshCw size={13} className={isLoading ? "animate-spin" : ""} />
          </Button>
        </div>

        {isLoading && (
          <div className="flex items-center justify-center py-10">
            <Loader2 size={18} className="animate-spin text-text-muted" />
          </div>
        )}

        {isError && (
          <p className="text-xs text-loss text-center py-6">
            Failed to load cron jobs. Backend may be offline.
          </p>
        )}

        {!isLoading && !isError && jobs.length === 0 && (
          <p className="text-xs text-text-muted text-center py-8">
            No cron jobs registered. Add schedules via the Python automation package.
          </p>
        )}

        {!isLoading && jobs.length > 0 && (
          <StaggeredList className="space-y-2">
            {jobs.map((job) => {
              const isWorking = pendingJob === job.name;
              const isPaused = job.status.toLowerCase() === "paused";
              return (
                <div
                  key={job.name}
                  className="bg-surface-base border border-border-default rounded-lg px-4 py-3 flex items-center gap-3"
                >
                  <StatusDot status={job.status} />
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-0.5">
                      <p className="text-xs font-semibold text-text-primary truncate">{job.name}</p>
                      <StatusBadge status={job.status} />
                    </div>
                    <div className="flex items-center gap-3 text-xs text-text-muted">
                      <span className="font-mono">{job.trigger_type}</span>
                      <span>Last: {formatLastRun(job.last_run)}</span>
                      <span>
                        Runs:{" "}
                        <span className="text-text-primary font-mono">{job.run_count}</span>
                      </span>
                      {job.error_count > 0 && (
                        <span className="text-loss font-mono">
                          Errors: {job.error_count}
                        </span>
                      )}
                    </div>
                    {job.description && (
                      <p className="text-xs text-text-muted mt-0.5 leading-tight">
                        {job.description}
                      </p>
                    )}
                  </div>
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => toggleJob(job)}
                    disabled={isWorking}
                    className="h-7 px-2.5 text-xs gap-1 border-border-default text-text-secondary hover:text-text-primary shrink-0"
                  >
                    {isWorking ? (
                      <Loader2 size={11} className="animate-spin" />
                    ) : isPaused ? (
                      <Play size={11} />
                    ) : (
                      <Pause size={11} />
                    )}
                    {isPaused ? "Resume" : "Pause"}
                  </Button>
                </div>
              );
            })}
          </StaggeredList>
        )}
      </GlassCard>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Section 3: Monitors — live running strategies
// ---------------------------------------------------------------------------

function StrategyStatusDot({ status }: { status: string }) {
  const lower = status.toLowerCase();
  if (lower === "running")  return <span className="ft-dot-running" />;
  if (lower === "stopping") return <span className="ft-dot-paused" />;
  if (lower === "error")    return <span className="ft-dot-kill" />;
  return <span className="ft-dot-paused" style={{ background: "#6b7280" }} />;
}

function strategyStatusBadge(status: string) {
  const lower = status.toLowerCase();
  if (lower === "running") {
    return <Badge className="text-xs bg-profit/10 text-profit border-0">Running</Badge>;
  }
  if (lower === "stopping") {
    return <Badge className="text-xs bg-atm-bg text-warning border-0">Stopping</Badge>;
  }
  if (lower === "error") {
    return <Badge className="text-xs bg-loss/10 text-loss border-0">Error</Badge>;
  }
  return <Badge className="text-xs bg-text-muted/10 text-text-muted border-0">{status}</Badge>;
}

function MonitorsSection() {
  const queryClient = useQueryClient();
  const [stoppingStrategy, setStoppingStrategy] = useState<string | null>(null);

  const { data, isLoading, isError } = useQuery({
    queryKey: ["runningStrategies"],
    queryFn: getRunningStrategies,
    refetchInterval: 5000,
  });

  const strategies: RunningStrategy[] = data ?? [];

  const stopMutation = useMutation({
    mutationFn: (name: string) => stopStrategy(name),
    onMutate: (name) => setStoppingStrategy(name),
    onSettled: () => {
      setStoppingStrategy(null);
      void queryClient.invalidateQueries({ queryKey: ["runningStrategies"] });
    },
  });

  const formatStartedAt = (val: string) => {
    try {
      return new Date(val).toLocaleString("en-IN", {
        timeZone: "Asia/Kolkata",
        dateStyle: "short",
        timeStyle: "short",
      });
    } catch {
      return val;
    }
  };

  return (
    <div className="space-y-4">
      <GlassCard className="p-6">
        <div className="flex items-center justify-between mb-4">
          <div>
            <h3 className="font-heading font-semibold text-lg text-text-primary">
              Live Strategy Monitors
            </h3>
            <p className="text-sm text-text-secondary mt-0.5">
              Auto-refreshes every 5 seconds. Stop any running strategy instantly.
            </p>
          </div>
          {isLoading && (
            <Loader2 size={14} className="animate-spin text-text-muted" />
          )}
        </div>

        {isError && (
          <p className="text-xs text-loss text-center py-6">
            Failed to load strategies. Backend may be offline.
          </p>
        )}

        {!isLoading && !isError && strategies.length === 0 && (
          <div className="flex flex-col items-center justify-center py-12 gap-2">
            <Activity size={28} className="text-text-muted opacity-40" />
            <p className="text-sm text-text-muted">No strategies running</p>
            <p className="text-xs text-text-muted opacity-60">
              Start a strategy from the Strategy Builder tool.
            </p>
          </div>
        )}

        {strategies.length > 0 && (
          <StaggeredList className="grid grid-cols-1 md:grid-cols-2 gap-3">
            {strategies.map((s) => (
              <div
                key={`${s.name}-${s.symbol}`}
                className="bg-surface-base border border-border-default rounded-lg p-4"
              >
                <div className="flex items-start justify-between gap-2 mb-3">
                  <div className="flex items-center gap-2 min-w-0">
                    <StrategyStatusDot status={s.status} />
                    <div className="min-w-0">
                      <p className="text-sm font-semibold text-text-primary truncate">{s.name}</p>
                      <p className="text-xs text-text-muted mt-0.5">
                        {s.symbol} · {s.exchange}
                      </p>
                    </div>
                  </div>
                  {strategyStatusBadge(s.status)}
                </div>
                <div className="grid grid-cols-2 gap-2 mb-3">
                  <div>
                    <p className="text-xs text-text-muted">Ticks processed</p>
                    <p className="text-sm font-mono font-bold text-text-primary">
                      {s.tick_count.toLocaleString()}
                    </p>
                  </div>
                  <div>
                    <p className="text-xs text-text-muted">Started at</p>
                    <p className="text-xs font-mono text-text-secondary">
                      {formatStartedAt(s.started_at)}
                    </p>
                  </div>
                </div>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => stopMutation.mutate(s.name)}
                  disabled={stoppingStrategy === s.name}
                  className="w-full h-7 text-xs gap-1.5 border-loss/30 text-loss hover:bg-loss/10 hover:border-loss"
                >
                  {stoppingStrategy === s.name ? (
                    <Loader2 size={11} className="animate-spin" />
                  ) : (
                    <Square size={11} />
                  )}
                  {stoppingStrategy === s.name ? "Stopping…" : "Stop Strategy"}
                </Button>
              </div>
            ))}
          </StaggeredList>
        )}
      </GlassCard>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Section 4: Logs — paginated audit logs
// ---------------------------------------------------------------------------

const PAGE_SIZE = 50;

function verdictClass(verdict: string): string {
  const lower = verdict.toLowerCase();
  if (lower === "pass") return "text-profit";
  if (lower === "fail") return "text-loss";
  if (lower === "warn") return "text-warning";
  return "text-text-muted";
}

function VerdictBadge({ verdict }: { verdict: string }) {
  const lower = verdict.toLowerCase();
  if (lower === "pass") {
    return <Badge className="text-xs bg-profit/10 text-profit border-0">PASS</Badge>;
  }
  if (lower === "fail") {
    return <Badge className="text-xs bg-loss/10 text-loss border-0">FAIL</Badge>;
  }
  if (lower === "warn") {
    return <Badge className="text-xs bg-atm-bg text-warning border-0">WARN</Badge>;
  }
  return (
    <Badge className="text-xs bg-text-muted/10 text-text-muted border-0">{verdict}</Badge>
  );
}

function LogsSection() {
  const today = new Date().toISOString().slice(0, 10);
  const [date, setDate] = useState(today);
  const [offset, setOffset] = useState(0);
  const [allLogs, setAllLogs] = useState<AuditLog[]>([]);
  const [total, setTotal] = useState(0);

  const { data, isFetching, isError, refetch } = useQuery({
    queryKey: ["auditLogs", date, offset],
    queryFn: () => getAuditLogs(date, PAGE_SIZE, offset),
  });

  // Accumulate logs as user pages through
  useEffect(() => {
    if (!data) return;
    if (offset === 0) {
      setAllLogs(data.logs);
    } else {
      setAllLogs((prev) => [...prev, ...data.logs]);
    }
    setTotal(data.total);
  }, [data, offset]);

  // Reset on date change
  const handleDateChange = (newDate: string) => {
    setDate(newDate);
    setOffset(0);
    setAllLogs([]);
    setTotal(0);
  };

  const handleLoadMore = () => {
    setOffset((prev) => prev + PAGE_SIZE);
  };

  const formatTs = (ts: string) => {
    try {
      return new Date(ts).toLocaleString("en-IN", {
        timeZone: "Asia/Kolkata",
        hour12: false,
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
      });
    } catch {
      return ts;
    }
  };

  const hasMore = allLogs.length < total;

  return (
    <div className="space-y-4">
      <GlassCard className="p-6">
        <div className="flex items-center justify-between mb-4 gap-4">
          <div>
            <h3 className="font-heading font-semibold text-lg text-text-primary">
              Execution Logs
            </h3>
            <p className="text-sm text-text-secondary mt-0.5">
              SEBI-compliant audit trail. Every trigger, condition, and order action is recorded.
            </p>
          </div>
          <div className="flex items-center gap-2 shrink-0">
            <Input
              type="date"
              value={date}
              onChange={(e) => handleDateChange(e.target.value)}
              className="h-8 text-xs w-36 bg-surface-base border-border-default text-text-primary"
            />
            <Button
              size="sm"
              variant="ghost"
              onClick={() => void refetch()}
              disabled={isFetching}
              className="h-7 w-7 p-0 text-text-muted hover:text-text-primary"
            >
              <RefreshCw size={13} className={isFetching ? "animate-spin" : ""} />
            </Button>
          </div>
        </div>

        {isError && (
          <p className="text-xs text-loss text-center py-6">
            Failed to load logs. Backend may be offline.
          </p>
        )}

        {!isError && allLogs.length === 0 && !isFetching && (
          <p className="text-xs text-text-muted text-center py-8">
            No logs for {date}. Logs appear once automations execute.
          </p>
        )}

        {allLogs.length > 0 && (
          <>
            <div className="text-xs text-text-muted mb-2">
              Showing {allLogs.length} of {total} entries
            </div>
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow className="border-border-default hover:bg-transparent">
                    <TableHead className="text-xs text-text-muted font-medium w-20">Time</TableHead>
                    <TableHead className="text-xs text-text-muted font-medium">Event</TableHead>
                    <TableHead className="text-xs text-text-muted font-medium">Strategy</TableHead>
                    <TableHead className="text-xs text-text-muted font-medium">Symbol</TableHead>
                    <TableHead className="text-xs text-text-muted font-medium">Action</TableHead>
                    <TableHead className="text-xs text-text-muted font-medium">Layer</TableHead>
                    <TableHead className="text-xs text-text-muted font-medium">Verdict</TableHead>
                    <TableHead className="text-xs text-text-muted font-medium">Reason</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {allLogs.map((log, i) => (
                    <TableRow
                      key={`${log.timestamp}-${i}`}
                      className="border-border-default hover:bg-surface-base"
                    >
                      <TableCell className="text-xs font-mono text-text-muted py-1.5 whitespace-nowrap">
                        {formatTs(log.timestamp)}
                      </TableCell>
                      <TableCell className="text-xs text-text-secondary py-1.5 whitespace-nowrap">
                        {log.event_type}
                      </TableCell>
                      <TableCell className="text-xs text-text-primary font-medium py-1.5">
                        {log.strategy}
                      </TableCell>
                      <TableCell className="text-xs font-mono text-text-secondary py-1.5 whitespace-nowrap">
                        {log.symbol}
                        {log.exchange ? (
                          <span className="text-text-muted"> · {log.exchange}</span>
                        ) : null}
                      </TableCell>
                      <TableCell className="text-xs text-text-secondary py-1.5">
                        {log.action}
                      </TableCell>
                      <TableCell className="text-xs font-mono text-text-muted py-1.5">
                        {log.layer}
                      </TableCell>
                      <TableCell className="py-1.5">
                        <VerdictBadge verdict={log.verdict} />
                      </TableCell>
                      <TableCell
                        className={`text-xs py-1.5 max-w-xs truncate ${verdictClass(log.verdict)}`}
                        title={log.reason}
                      >
                        {log.reason}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>

            {hasMore && (
              <div className="flex justify-center mt-4">
                <Button
                  size="sm"
                  variant="outline"
                  onClick={handleLoadMore}
                  disabled={isFetching}
                  className="h-8 px-6 text-xs border-border-default text-text-secondary hover:text-text-primary"
                >
                  {isFetching ? (
                    <Loader2 size={12} className="animate-spin mr-1.5" />
                  ) : null}
                  Load More ({total - allLogs.length} remaining)
                </Button>
              </div>
            )}
          </>
        )}

        {isFetching && allLogs.length === 0 && (
          <div className="flex items-center justify-center py-10">
            <Loader2 size={18} className="animate-spin text-text-muted" />
          </div>
        )}
      </GlassCard>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Telegram test panel
// ---------------------------------------------------------------------------

function TelegramTestPanel() {
  const DEFAULT_MESSAGE = "FlintTrade test alert — connection working!";
  const [message, setMessage] = useState(DEFAULT_MESSAGE);
  const [toastMsg, setToastMsg] = useState<string | null>(null);
  const dismissToast = useCallback(() => setToastMsg(null), []);

  const mutation = useMutation({
    mutationFn: (msg: string) => sendTelegram(msg),
    onSuccess: () => {
      setToastMsg("Telegram alert sent successfully");
    },
  });

  const handleSend = () => {
    const trimmed = message.trim();
    if (!trimmed) return;
    mutation.mutate(trimmed);
  };

  return (
    <div className="space-y-3">
      <div className="flex gap-2">
        <Input
          value={message}
          onChange={(e) => setMessage(e.target.value)}
          placeholder="Enter test message…"
          className="flex-1 bg-surface-base border-border-default text-text-primary text-xs h-8"
          disabled={mutation.isPending}
          onKeyDown={(e) => {
            if (e.key === "Enter") handleSend();
          }}
        />
        <Button
          size="sm"
          variant="outline"
          onClick={handleSend}
          disabled={mutation.isPending || !message.trim()}
          className="h-8 px-3 gap-1.5 border-border-default text-text-primary hover:text-accent hover:border-accent"
        >
          {mutation.isPending ? (
            <Loader2 size={13} className="animate-spin" />
          ) : (
            <Send size={13} />
          )}
          <span className="text-xs">{mutation.isPending ? "Sending…" : "Send Test"}</span>
        </Button>
      </div>

      {mutation.isError && (
        <p className="text-xs text-loss">
          {mutation.error instanceof Error
            ? mutation.error.message
            : "Failed to send Telegram alert"}
        </p>
      )}

      {toastMsg && <InlineToast message={toastMsg} onDismiss={dismissToast} />}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Section 5: Settings — kill switch + safety config + Telegram
// ---------------------------------------------------------------------------

function AutomationSettingsSection() {
  const queryClient = useQueryClient();
  const [killReason, setKillReason] = useState("");
  const [toast, setToast] = useState<{ msg: string; variant: "success" | "error" } | null>(null);
  const dismissToast = useCallback(() => setToast(null), []);
  const [localConfig, setLocalConfig] = useState<Partial<SafetyConfig>>({});
  const [configDirty, setConfigDirty] = useState(false);

  const {
    data: safetyConfig,
    isLoading: loadingConfig,
    isError: configError,
  } = useQuery({
    queryKey: ["safetyConfig"],
    queryFn: getSafetyConfig,
  });

  // Populate local editable state when data arrives
  useEffect(() => {
    if (safetyConfig && !configDirty) {
      setLocalConfig(safetyConfig);
    }
  }, [safetyConfig, configDirty]);

  const updateConfigMutation = useMutation({
    mutationFn: (cfg: Partial<SafetyConfig>) => updateSafetyConfig(cfg),
    onSuccess: () => {
      setConfigDirty(false);
      void queryClient.invalidateQueries({ queryKey: ["safetyConfig"] });
      setToast({ msg: "Safety config saved", variant: "success" });
    },
    onError: (err: Error) => {
      setToast({ msg: err.message ?? "Failed to save config", variant: "error" });
    },
  });

  const activateKillMutation = useMutation({
    mutationFn: (reason: string) => activateKillSwitch(reason),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["safetyConfig"] });
      setToast({ msg: "Kill switch activated", variant: "success" });
      setKillReason("");
    },
    onError: (err: Error) => {
      setToast({ msg: err.message ?? "Failed to activate kill switch", variant: "error" });
    },
  });

  const resetKillMutation = useMutation({
    mutationFn: () => resetKillSwitch(),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["safetyConfig"] });
      setToast({ msg: "Kill switch reset — trading resumed", variant: "success" });
    },
    onError: (err: Error) => {
      setToast({ msg: err.message ?? "Failed to reset kill switch", variant: "error" });
    },
  });

  const killSwitchActive = safetyConfig?.kill_switch_active ?? false;

  const updateField = <K extends keyof SafetyConfig>(key: K, value: SafetyConfig[K]) => {
    setLocalConfig((prev) => ({ ...prev, [key]: value }));
    setConfigDirty(true);
  };

  const handleSaveConfig = () => {
    updateConfigMutation.mutate(localConfig);
  };

  const numericField = (
    label: string,
    key: keyof SafetyConfig,
    unit?: string,
  ) => {
    const raw = localConfig[key];
    const numVal = typeof raw === "number" ? raw : 0;
    return (
      <div className="space-y-1">
        <label className="text-xs text-text-muted">{label}</label>
        <div className="flex items-center gap-1.5">
          <Input
            type="number"
            value={numVal}
            onChange={(e) =>
              updateField(key, Number(e.target.value) as SafetyConfig[typeof key])
            }
            className="h-8 text-xs bg-surface-base border-border-default text-text-primary w-28"
          />
          {unit && <span className="text-xs text-text-muted">{unit}</span>}
        </div>
      </div>
    );
  };

  return (
    <div className="space-y-4">
      {/* Toast */}
      {toast && (
        <InlineToast message={toast.msg} variant={toast.variant} onDismiss={dismissToast} />
      )}

      <StaggeredList className="space-y-4">
        {/* Kill Switch */}
        <GlassCard className="p-6">
          <div className="flex items-center gap-2 mb-1">
            {killSwitchActive ? (
              <>
                <span className="ft-dot-kill" />
                <ShieldAlert size={18} className="text-loss" />
              </>
            ) : (
              <>
                <span className="ft-dot-running" />
                <ShieldCheck size={18} className="text-profit" />
              </>
            )}
            <h3 className="font-heading font-semibold text-lg text-text-primary">Kill Switch</h3>
            {killSwitchActive ? (
              <Badge className="ml-auto text-xs bg-loss/10 text-loss border-0">ACTIVE</Badge>
            ) : (
              <Badge className="ml-auto text-xs bg-profit/10 text-profit border-0">INACTIVE</Badge>
            )}
          </div>
          <p className="text-sm text-text-secondary mb-4 leading-relaxed">
            Emergency stop for all automated strategies. Cancels pending orders and closes
            positions immediately. Also available via Telegram /kill command.
          </p>

          {killSwitchActive ? (
            <div className="space-y-3">
              <div className="flex items-center gap-2 p-3 rounded-lg bg-loss/10 border border-loss/20">
                <AlertTriangle size={14} className="text-loss flex-none" />
                <p className="text-xs text-loss">
                  Kill switch is active. All automation is halted.
                </p>
              </div>
              <Button
                onClick={() => resetKillMutation.mutate()}
                disabled={resetKillMutation.isPending}
                className="bg-profit/20 hover:bg-profit/30 text-profit border border-profit/30 h-9 px-5 text-sm gap-2"
                variant="outline"
              >
                {resetKillMutation.isPending ? (
                  <Loader2 size={14} className="animate-spin" />
                ) : (
                  <ShieldCheck size={14} />
                )}
                Reset Kill Switch — Resume Trading
              </Button>
            </div>
          ) : (
            <div className="space-y-3">
              <div className="flex gap-2">
                <Input
                  value={killReason}
                  onChange={(e) => setKillReason(e.target.value)}
                  placeholder="Reason (optional, logged for audit)"
                  className="flex-1 h-9 text-xs bg-surface-base border-border-default text-text-primary"
                />
                <Button
                  onClick={() => activateKillMutation.mutate(killReason)}
                  disabled={activateKillMutation.isPending}
                  variant="outline"
                  className="bg-loss/10 hover:bg-loss/20 text-loss border border-loss/30 h-9 px-5 text-sm gap-2 shrink-0"
                >
                  {activateKillMutation.isPending ? (
                    <Loader2 size={14} className="animate-spin" />
                  ) : (
                    <ShieldAlert size={14} />
                  )}
                  Activate Kill Switch
                </Button>
              </div>
            </div>
          )}
        </GlassCard>

        {/* Safety Config */}
        <GlassCard className="p-6">
          <h3 className="font-heading font-semibold text-lg text-text-primary mb-1">
            Safety Configuration
          </h3>
          <p className="text-sm text-text-secondary mb-4 leading-relaxed">
            Hard limits enforced by the 5-layer safety system. These constraints cannot be
            bypassed by any automation or strategy.
          </p>

          {loadingConfig && (
            <div className="flex items-center justify-center py-8">
              <Loader2 size={18} className="animate-spin text-text-muted" />
            </div>
          )}

          {configError && (
            <p className="text-xs text-loss text-center py-4">
              Failed to load safety config. Backend may be offline.
            </p>
          )}

          {!loadingConfig && !configError && safetyConfig && (
            <div className="space-y-4">
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                {numericField("Max Positions", "max_positions")}
                {numericField("Max Margin", "max_margin_pct", "%")}
                {numericField("Daily Loss — Pause", "daily_loss_pause_pct", "%")}
                {numericField("Daily Loss — Kill", "daily_loss_kill_pct", "%")}
                {numericField("Max Net Delta", "max_net_delta")}
                {numericField("Max Net Vega", "max_net_vega")}
              </div>

              {configDirty && (
                <div className="flex justify-end pt-2">
                  <Button
                    size="sm"
                    onClick={handleSaveConfig}
                    disabled={updateConfigMutation.isPending}
                    className="h-8 px-5 text-xs gap-1.5"
                  >
                    {updateConfigMutation.isPending ? (
                      <Loader2 size={12} className="animate-spin" />
                    ) : (
                      <CheckCircle2 size={12} />
                    )}
                    Save Config
                  </Button>
                </div>
              )}
            </div>
          )}
        </GlassCard>

        {/* Telegram */}
        <GlassCard className="p-6">
          <h3 className="font-heading font-semibold text-lg text-text-primary mb-1">
            Telegram Alerts
          </h3>
          <p className="text-sm text-text-secondary mb-4 leading-relaxed">
            Configure bot token and chat ID in workspace.json. Test the connection below.
            All trade notifications, P&L updates, and error alerts are sent to Telegram.
          </p>
          <TelegramTestPanel />
        </GlassCard>
      </StaggeredList>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main — query kill switch & monitor counts for rail dots
// ---------------------------------------------------------------------------

export default function AutomateRoute() {
  const [activeSection, setActiveSection] = useState<SectionId>("flows");

  // Lightweight queries for rail status dots — no extra network cost since
  // the same keys are fetched by each section when it mounts.
  const { data: safetyData } = useQuery({
    queryKey: ["safetyConfig"],
    queryFn: getSafetyConfig,
  });

  const { data: strategiesData } = useQuery({
    queryKey: ["runningStrategies"],
    queryFn: getRunningStrategies,
    refetchInterval: 10000,
  });

  const killSwitchActive = safetyData?.kill_switch_active ?? false;
  const runningCount = (strategiesData ?? []).filter(
    (s) => s.status.toLowerCase() === "running",
  ).length;

  const sectionContent: Record<SectionId, React.ReactNode> = {
    flows:     <FlowsSection />,
    schedules: <SchedulesSection />,
    monitors:  <MonitorsSection />,
    logs:      <LogsSection />,
    settings:  <AutomationSettingsSection />,
  };

  return (
    <div className="h-full bg-surface-base flex flex-col overflow-hidden">
      {/* Header */}
      <div className="border-b border-border-default bg-surface-card px-6 py-4 shrink-0">
        <div className="flex items-center gap-3">
          <Workflow className="w-6 h-6 text-accent" />
          <div>
            <h1 className="font-heading font-bold text-lg text-text-primary">Automation Hub</h1>
            <p className="text-xxs text-text-muted">
              54-node flow builder, cron scheduler, Telegram kill switch — no other broker has this
            </p>
          </div>
          {killSwitchActive && (
            <div className="ml-auto flex items-center gap-1.5 px-3 py-1 rounded-full bg-loss/10 border border-loss/30">
              <span className="ft-dot-kill" />
              <span className="text-xs text-loss font-medium">Kill Switch Active</span>
            </div>
          )}
        </div>
      </div>

      <div className="flex flex-1 overflow-hidden">
        {/* Icon rail — replaces old 224px sidebar */}
        <IconRail
          activeSection={activeSection}
          onSelect={setActiveSection}
          killSwitchActive={killSwitchActive}
          runningCount={runningCount}
        />

        {/* Content with TabTransition crossfade */}
        <ScrollArea className="flex-1">
          <TabTransition tabKey={activeSection} className="p-6 max-w-4xl">
            {sectionContent[activeSection]}
          </TabTransition>
        </ScrollArea>
      </div>
    </div>
  );
}
