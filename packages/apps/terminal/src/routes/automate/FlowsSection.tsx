/**
 * FlowsSection — Flow Builder tab.
 * Shows the 54-node drag-and-drop palette grouped by category,
 * node-type stats, and the registered webhook list (create / delete).
 */

import { useState, useCallback } from "react";
import {
  Plus, Trash2, Loader2, ChevronDown, ChevronRight,
  // Trigger icons
  Clock, Bell, Webhook, Globe,
  // Action icons
  ShoppingCart, Zap, TrendingUp, Layers, XCircle, LogOut,
  X, Edit, ShoppingBag, Scissors,
  // Condition icons
  Search, Wallet, Timer, GitCompare,
  // Logic icons
  GitMerge, GitBranch, ToggleLeft,
  // Data icons
  BarChart3, FileSearch, CandlestickChart, Briefcase,
  Calendar, BarChart, BarChart2, Hash, Tag, BookOpen,
  FileText, Table, Activity, Table2, CalendarOff, Clock3,
  // Streaming icons
  Radio, Unplug,
  // Risk icons
  PieChart, IndianRupee, Calculator,
  // Utility icons
  Send, Square, Variable,
} from "lucide-react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import {
  Table as UITable, TableBody, TableCell, TableHead, TableHeader, TableRow,
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
import type { LucideIcon } from "lucide-react";

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
  gocharting:  "GoCharting",
  custom:      "Custom",
};

// ---------------------------------------------------------------------------
// Node palette — all 54 node types
// ---------------------------------------------------------------------------

interface NodeDef {
  id: string;
  label: string;
  icon: LucideIcon;
  description: string;
}

interface NodeCategory {
  name: string;
  color: string;
  nodes: NodeDef[];
}

const NODE_CATEGORIES: NodeCategory[] = [
  {
    name: "Triggers",
    color: "text-green-400",
    nodes: [
      { id: "start",          label: "Start",             icon: Clock,           description: "Schedule: one-time, daily, weekly, interval" },
      { id: "priceAlert",     label: "Price Alert",       icon: Bell,            description: "Trigger on price crossing a threshold" },
      { id: "webhookTrigger", label: "Webhook Trigger",   icon: Webhook,         description: "Trigger from inbound webhook" },
      { id: "httpRequest",    label: "HTTP Request",      icon: Globe,           description: "Outbound HTTP request" },
    ],
  },
  {
    name: "Actions",
    color: "text-blue-400",
    nodes: [
      { id: "placeOrder",        label: "Place Order",         icon: ShoppingCart, description: "Regular order via OpenAlgo" },
      { id: "smartOrder",        label: "Smart Order",         icon: Zap,          description: "Smart order with position sizing" },
      { id: "optionsOrder",      label: "Options Order",       icon: TrendingUp,   description: "Options order by strike offset" },
      { id: "optionsMultiOrder", label: "Options Multi Order", icon: Layers,       description: "Multi-leg options (straddle, etc.)" },
      { id: "cancelAllOrders",   label: "Cancel All Orders",   icon: XCircle,      description: "Cancel all open orders" },
      { id: "closePositions",    label: "Close Positions",     icon: LogOut,       description: "Close all open positions" },
      { id: "cancelOrder",       label: "Cancel Order",        icon: X,            description: "Cancel a specific order" },
      { id: "modifyOrder",       label: "Modify Order",        icon: Edit,         description: "Modify an existing order" },
      { id: "basketOrder",       label: "Basket Order",        icon: ShoppingBag,  description: "Multiple orders in one call" },
      { id: "splitOrder",        label: "Split Order",         icon: Scissors,     description: "Split large order into slices" },
    ],
  },
  {
    name: "Conditions",
    color: "text-yellow-400",
    nodes: [
      { id: "positionCheck",  label: "Position Check",   icon: Search,     description: "Check if position exists" },
      { id: "fundCheck",      label: "Fund Check",       icon: Wallet,     description: "Check available funds" },
      { id: "timeWindow",     label: "Time Window",      icon: Clock,      description: "Check if within time range" },
      { id: "timeCondition",  label: "Time Condition",   icon: Timer,      description: "Time before/after/at check" },
      { id: "priceCondition", label: "Price Condition",  icon: GitCompare, description: "Compare price to value" },
    ],
  },
  {
    name: "Logic Gates",
    color: "text-purple-400",
    nodes: [
      { id: "andGate", label: "AND Gate",  icon: GitMerge,   description: "All inputs must be true" },
      { id: "orGate",  label: "OR Gate",   icon: GitBranch,  description: "Any input can be true" },
      { id: "notGate", label: "NOT Gate",  icon: ToggleLeft,  description: "Invert boolean input" },
    ],
  },
  {
    name: "Data",
    color: "text-cyan-400",
    nodes: [
      { id: "getQuote",        label: "Get Quote",        icon: BarChart3,        description: "Fetch real-time quote" },
      { id: "getDepth",        label: "Get Depth",        icon: Layers,           description: "Fetch market depth" },
      { id: "getOrderStatus",  label: "Get Order Status", icon: FileSearch,       description: "Get status of an order" },
      { id: "history",         label: "History",          icon: CandlestickChart, description: "OHLCV candle data" },
      { id: "openPosition",    label: "Open Position",    icon: Briefcase,        description: "Get position details" },
      { id: "expiry",          label: "Expiry",           icon: Calendar,         description: "Get expiry dates" },
      { id: "intervals",       label: "Intervals",        icon: BarChart,         description: "Supported candle intervals" },
      { id: "multiQuotes",     label: "Multi Quotes",     icon: BarChart2,        description: "Quotes for multiple symbols" },
      { id: "symbol",          label: "Symbol Lookup",    icon: Hash,             description: "Look up symbol details" },
      { id: "optionSymbol",    label: "Option Symbol",    icon: Tag,              description: "Resolve option symbol" },
      { id: "orderBook",       label: "Order Book",       icon: BookOpen,         description: "All orders today" },
      { id: "tradeBook",       label: "Trade Book",       icon: FileText,         description: "All executed trades" },
      { id: "positionBook",    label: "Position Book",    icon: Table,            description: "All current positions" },
      { id: "syntheticFuture", label: "Synthetic Future", icon: Activity,         description: "Synthetic future price" },
      { id: "optionChain",     label: "Option Chain",     icon: Table2,           description: "Full option chain" },
      { id: "search",          label: "Search Symbol",    icon: Search,           description: "Search symbols by name" },
      { id: "holidays",        label: "Holidays",         icon: CalendarOff,      description: "Market holidays list" },
      { id: "timings",         label: "Market Timings",   icon: Clock3,           description: "Market open/close times" },
    ],
  },
  {
    name: "Streaming",
    color: "text-emerald-400",
    nodes: [
      { id: "subscribeLtp",   label: "Subscribe LTP",   icon: Radio,    description: "Real-time LTP via WebSocket" },
      { id: "subscribeQuote",  label: "Subscribe Quote", icon: Radio,    description: "Real-time quote via WebSocket" },
      { id: "subscribeDepth",  label: "Subscribe Depth", icon: Radio,    description: "Real-time depth via WebSocket" },
      { id: "unsubscribe",     label: "Unsubscribe",     icon: Unplug, description: "Unsubscribe from stream" },
    ],
  },
  {
    name: "Risk",
    color: "text-orange-400",
    nodes: [
      { id: "holdings", label: "Holdings", icon: PieChart,    description: "Portfolio holdings" },
      { id: "funds",    label: "Funds",    icon: IndianRupee, description: "Available margin/funds" },
      { id: "margin",   label: "Margin",   icon: Calculator,  description: "Margin calculation" },
    ],
  },
  {
    name: "Utilities",
    color: "text-gray-400",
    nodes: [
      { id: "telegramAlert",  label: "Telegram Alert",   icon: Send,       description: "Send Telegram notification" },
      { id: "delay",          label: "Delay",             icon: Timer,      description: "Wait for a duration" },
      { id: "waitUntil",      label: "Wait Until",        icon: Clock,      description: "Wait until a specific time" },
      { id: "group",          label: "Group",             icon: Square,     description: "Visual grouping (no logic)" },
      { id: "variable",       label: "Variable",          icon: Variable,   description: "Set/compute a variable" },
      { id: "mathExpression", label: "Math Expression",   icon: Calculator, description: "Evaluate math expression" },
      { id: "log",            label: "Log",               icon: FileText,   description: "Log a message" },
    ],
  },
];

const TOTAL_NODE_COUNT = NODE_CATEGORIES.reduce((sum, cat) => sum + cat.nodes.length, 0);

// ---------------------------------------------------------------------------
// CollapsibleCategory — expandable node group
// ---------------------------------------------------------------------------

function CollapsibleCategory({ category }: { category: NodeCategory }) {
  const [open, setOpen] = useState(true);

  return (
    <div className="border border-border-default rounded-lg overflow-hidden">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center justify-between px-3 py-2 bg-surface-base hover:bg-surface-card transition-colors text-left"
      >
        <div className="flex items-center gap-2">
          <span className={`text-xs font-semibold ${category.color}`}>{category.name}</span>
          <Badge className="text-[10px] bg-surface-card text-text-muted border-0 px-1.5 py-0">
            {category.nodes.length}
          </Badge>
        </div>
        {open ? <ChevronDown size={12} className="text-text-muted" /> : <ChevronRight size={12} className="text-text-muted" />}
      </button>
      {open && (
        <div className="grid grid-cols-2 gap-1 p-2 bg-surface-base/50">
          {category.nodes.map((node) => {
            const Icon = node.icon;
            return (
              <div
                key={node.id}
                className="flex items-center gap-2 px-2 py-1.5 rounded-md bg-surface-card border border-border-default hover:border-accent/50 transition-colors cursor-grab group"
                title={node.description}
                draggable
                onDragStart={(e) => {
                  e.dataTransfer.setData("application/flow-node", node.id);
                  e.dataTransfer.effectAllowed = "move";
                }}
              >
                <Icon size={12} className="text-text-muted group-hover:text-accent shrink-0" />
                <span className="text-[10px] text-text-secondary group-hover:text-text-primary truncate">
                  {node.label}
                </span>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

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
    <div className="space-y-4" data-tour-target="flow-builder">
      <StaggeredList className="space-y-4">

        {/* Overview */}
        <GlassCard className="p-6">
          <h3 className="font-heading font-semibold text-lg text-text-primary mb-2">Flow Builder</h3>
          <p className="text-sm text-text-secondary leading-relaxed mb-4">
            Build broker-workflow automations visually with a {TOTAL_NODE_COUNT}-node drag-and-drop flow builder.
            Connect market data triggers, conditions, and order actions without writing code.
            Flows run server-side and persist across sessions.
          </p>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
            <div className="bg-surface-base border border-border-default rounded-lg p-4">
              <p className="text-xs text-text-muted mb-1">Node Types</p>
              <p className="text-2xl font-mono font-bold text-text-primary">{TOTAL_NODE_COUNT}</p>
            </div>
            <div className="bg-surface-base border border-border-default rounded-lg p-4">
              <p className="text-xs text-text-muted mb-1">Categories</p>
              <p className="text-2xl font-mono font-bold text-text-primary">{NODE_CATEGORIES.length}</p>
            </div>
            <div className="bg-surface-base border border-border-default rounded-lg p-4">
              <p className="text-xs text-text-muted mb-1">Execution</p>
              <p className="text-2xl font-mono font-bold text-accent">Server-side</p>
            </div>
          </div>
        </GlassCard>

        {/* Node palette — collapsible by category */}
        <GlassCard className="p-6">
          <h3 className="font-heading font-semibold text-sm text-text-primary mb-3">Node Palette</h3>
          <p className="text-xs text-text-muted mb-3">
            Drag nodes onto the canvas to build your flow. {TOTAL_NODE_COUNT} nodes across {NODE_CATEGORIES.length} categories.
          </p>
          <div className="space-y-2">
            {NODE_CATEGORIES.map((cat) => (
              <CollapsibleCategory key={cat.name} category={cat} />
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
                  <Select value={form.type} onValueChange={(v) => setForm((f) => ({ ...f, type: v as WebhookFormState["type"] }))}>
                    <SelectTrigger className="w-full h-8 text-xs bg-surface-card border-border-default">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="tradingview">TradingView</SelectItem>
                      <SelectItem value="chartink">ChartInk</SelectItem>
                      <SelectItem value="custom">Custom</SelectItem>
                    </SelectContent>
                  </Select>
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
            <UITable>
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
            </UITable>
          )}
        </GlassCard>

      </StaggeredList>
    </div>
  );
}
