/**
 * SmartOrderWidget — liquidity-aware order slicing through the gated path.
 *
 * Front-end for POST /api/v1/orders/smart-route: the backend slices the
 * parent order by urgency (high = single market order, medium = depth-aware
 * chunks, low = TWAP over a window) and EVERY child independently traverses
 * the full gated execution path (SafetySystem L1–L5 → gate_order →
 * BrokerRouter → adapter).
 *
 * Honest gating: the feature is live-mode only and disabled by default
 * (workspace.json brokers.smart_routing.enabled) — the widget surfaces the
 * backend's actionable refusal messages verbatim and never fabricates
 * progress. Child rows are real job state polled from the backend.
 */

import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { GitFork, Loader2, Send } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { cn } from "@/lib/utils";
import { useModeStore } from "@/stores/modeStore";
import {
  getSmartRouteJob,
  startSmartRoute,
  type SmartRouteJob,
} from "@/services/ftApi";
import { emitNotification } from "@/components/NotificationCentre/useNotificationFeed";

const EXCHANGES = ["NSE", "NFO", "BSE", "BFO", "MCX", "CDS"] as const;

const URGENCY_OPTIONS = [
  { value: "high", label: "High — single market order, immediate" },
  { value: "medium", label: "Medium — depth-aware chunks, 1–5s apart" },
  { value: "low", label: "Low — TWAP slices over the configured window" },
] as const;

function StatusPill({ status }: { status: SmartRouteJob["status"] }) {
  const cls =
    status === "done"
      ? "bg-profit/10 text-profit border-profit/30"
      : status === "error"
        ? "bg-loss/10 text-loss border-loss/30"
        : "bg-accent/10 text-accent border-accent/30";
  return (
    <span className={cn("text-xxs px-1.5 py-px rounded border font-medium", cls)}>
      {status === "running" ? "Routing…" : status === "done" ? "Complete" : "Error"}
    </span>
  );
}

export default function SmartOrderWidget() {
  const appMode = useModeStore((s) => s.mode);
  const isLive = appMode === "live";

  const [symbol, setSymbol] = useState("");
  const [exchange, setExchange] = useState<string>("NSE");
  const [action, setAction] = useState<"BUY" | "SELL">("BUY");
  const [quantity, setQuantity] = useState("");
  const [urgency, setUrgency] = useState<"low" | "medium" | "high">("medium");
  const [maxSlippage, setMaxSlippage] = useState("20");
  const [jobId, setJobId] = useState<string | null>(null);

  const startMutation = useMutation({
    mutationFn: startSmartRoute,
    onSuccess: (job) => {
      setJobId(job.job_id);
      emitNotification({
        category: "system",
        title: "Smart route started",
        body: `${job.action} ${job.total_quantity} ${job.symbol} (${job.urgency} urgency).`,
      });
    },
  });

  const jobQuery = useQuery({
    queryKey: ["smartRoute", jobId],
    queryFn: () => getSmartRouteJob(jobId as string),
    enabled: !!jobId,
    refetchInterval: (q) => (q.state.data?.status === "running" ? 1000 : false),
    initialData: () => startMutation.data,
  });

  const job = jobQuery.data ?? startMutation.data ?? null;
  const qty = parseInt(quantity, 10);
  const canSubmit =
    isLive && !startMutation.isPending && symbol.trim().length > 0 && Number.isFinite(qty) && qty > 0;

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!canSubmit) return;
    startMutation.mutate({
      symbol: symbol.trim().toUpperCase(),
      exchange,
      action,
      quantity: qty,
      urgency,
      max_slippage_bps: parseInt(maxSlippage, 10) || 20,
    });
  }

  return (
    <div className="h-full flex flex-col bg-surface-base overflow-hidden">
      {/* Header */}
      <div className="flex-none flex items-center gap-2 px-3 py-2 bg-surface-card border-b border-border-default">
        <GitFork size={13} className="text-text-muted" aria-hidden="true" />
        <span className="text-xs font-medium text-text-primary">Smart Order</span>
        <div className="flex-1" />
        {job && <StatusPill status={job.status} />}
      </div>

      <div className="flex-1 overflow-auto p-3 space-y-3">
        {!isLive && (
          <p className="text-xs text-warning bg-warning/10 border border-warning/30 rounded px-2.5 py-1.5">
            Smart routing places real orders and serves live mode only — switch
            to Live to use it. It also needs{" "}
            <code className="font-mono">brokers.smart_routing.enabled</code> in
            workspace.json.
          </p>
        )}

        {/* Order form */}
        <form className="space-y-2" onSubmit={handleSubmit}>
          <div className="flex items-center gap-2">
            <Input
              value={symbol}
              onChange={(e) => setSymbol(e.target.value)}
              placeholder="Symbol (e.g. RELIANCE)"
              aria-label="Smart order symbol"
              className="h-7 flex-1 text-xs font-mono"
            />
            <Select value={exchange} onValueChange={setExchange}>
              <SelectTrigger className="h-7 w-20 text-xs" aria-label="Exchange">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {EXCHANGES.map((x) => (
                  <SelectItem key={x} value={x} className="text-xs">
                    {x}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className="flex items-center gap-2">
            <div role="group" aria-label="Order side" className="flex rounded border border-border-default overflow-hidden">
              {(["BUY", "SELL"] as const).map((side) => (
                <button
                  key={side}
                  type="button"
                  onClick={() => setAction(side)}
                  aria-pressed={action === side}
                  className={cn(
                    "px-3 h-7 text-xs font-semibold transition-colors",
                    action === side
                      ? side === "BUY"
                        ? "bg-profit text-white"
                        : "bg-loss text-white"
                      : "bg-surface-elevated text-text-muted hover:text-text-primary",
                  )}
                >
                  {side}
                </button>
              ))}
            </div>
            <Input
              value={quantity}
              onChange={(e) => setQuantity(e.target.value)}
              placeholder="Quantity"
              inputMode="numeric"
              aria-label="Smart order quantity"
              className="h-7 w-24 text-xs font-mono"
            />
            <Input
              value={maxSlippage}
              onChange={(e) => setMaxSlippage(e.target.value)}
              inputMode="numeric"
              aria-label="Max slippage in basis points"
              title="Maximum slippage budget (basis points)"
              className="h-7 w-20 text-xs font-mono"
            />
            <span className="text-xxs text-text-muted">bps</span>
          </div>

          <div className="flex items-center gap-2">
            <Select value={urgency} onValueChange={(v) => setUrgency(v as typeof urgency)}>
              <SelectTrigger className="h-7 flex-1 text-xs" aria-label="Routing urgency">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {URGENCY_OPTIONS.map((o) => (
                  <SelectItem key={o.value} value={o.value} className="text-xs">
                    {o.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Button type="submit" size="sm" disabled={!canSubmit} className="gap-1.5 h-7">
              {startMutation.isPending ? (
                <Loader2 size={13} className="animate-spin" />
              ) : (
                <Send size={13} />
              )}
              Route order
            </Button>
          </div>
        </form>

        {startMutation.isError && (
          <p role="alert" className="text-xs text-loss">
            {startMutation.error instanceof Error
              ? startMutation.error.message
              : "Smart route failed"}
          </p>
        )}

        {/* Live job state */}
        {job && (
          <div className="space-y-2">
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xxs text-text-muted">
              <span className="font-mono text-text-primary">
                {job.action} {job.total_quantity} {job.symbol}
              </span>
              <span>filled {job.filled_quantity}/{job.total_quantity}</span>
              <span>urgency {job.urgency}</span>
              {job.average_slippage_bps > 0 && (
                <span>avg slippage {job.average_slippage_bps.toFixed(1)} bps</span>
              )}
            </div>

            {job.error && (
              <p role="alert" className="text-xs text-loss">
                {job.error}
              </p>
            )}

            {job.child_orders.length > 0 && (
              <table className="w-full text-xxs" aria-label="Child orders">
                <thead>
                  <tr className="text-text-muted border-b border-border-subtle">
                    <th className="text-left py-1 font-normal">#</th>
                    <th className="text-right py-1 font-normal">Qty</th>
                    <th className="text-left py-1 pl-3 font-normal">Status</th>
                    <th className="text-left py-1 pl-3 font-normal">Order ID / Error</th>
                  </tr>
                </thead>
                <tbody>
                  {job.child_orders.map((child, i) => (
                    <tr key={i} className="border-b border-border-subtle/50">
                      <td className="py-1 text-text-muted">{i + 1}</td>
                      <td className="py-1 text-right font-mono text-text-primary">{child.quantity}</td>
                      <td
                        className={cn(
                          "py-1 pl-3",
                          child.status === "placed"
                            ? "text-profit"
                            : child.status === "failed"
                              ? "text-loss"
                              : "text-text-muted",
                        )}
                      >
                        {child.status}
                      </td>
                      <td className="py-1 pl-3 font-mono text-text-secondary truncate max-w-[160px]">
                        {child.order_id || child.error || "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        )}

        {!job && isLive && (
          <p className="text-xs text-text-muted">
            No smart route yet — large orders get sliced by liquidity; every
            child order still passes the full safety gate.
          </p>
        )}
      </div>
    </div>
  );
}
