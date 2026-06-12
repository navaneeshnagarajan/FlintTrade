/**
 * ReconciliationWidget — broker-vs-FlintTrade reconciliation observability.
 *
 * Renders the engine ReconciliationRunner's persisted history per native
 * broker target: a clean/severity badge, severity counts, and the last run
 * time, with the latest report's diffs expandable per row. "Reconcile now"
 * triggers an operator `run_once()` cycle through the backend and refreshes
 * the table.
 *
 * API (via lib/reconciliationApi):
 *   GET  /ft-api/api/v1/reconciliation/status
 *   GET  /ft-api/api/v1/reconciliation/reports?broker=&account_id=&limit=
 *   POST /ft-api/api/v1/reconciliation/run
 *
 * Honesty: reconciliation only runs against ACTIVE native broker sessions.
 * When none exist (the runner is dormant) the widget says so plainly rather
 * than rendering fabricated targets.
 */

import { memo, useState } from "react";
import {
  AlertTriangle,
  ChevronDown,
  ChevronRight,
  Loader2,
  RefreshCw,
  Scale,
  ShieldCheck,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { emitNotification } from "@/components/NotificationCentre/useNotificationFeed";
import {
  useReconciliationReports,
  useReconciliationStatus,
  useRunReconciliation,
  type ReconciliationReport,
  type ReconciliationTargetStatus,
} from "@/lib/reconciliationApi";
import type { WidgetProps } from "@/types/widgets";

// ---------------------------------------------------------------------------
// Formatting helpers
// ---------------------------------------------------------------------------

function formatReportTime(iso: string): string {
  if (!iso) return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleString("en-IN", {
    timeZone: "Asia/Kolkata",
    hour12: false,
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

// ---------------------------------------------------------------------------
// Badges
// ---------------------------------------------------------------------------

function StatusBadge({ target }: { target: ReconciliationTargetStatus }) {
  if (target.clean) {
    return (
      <Badge className="text-xxs bg-profit/10 text-profit border-0 gap-1">
        <ShieldCheck size={10} aria-hidden="true" /> Clean
      </Badge>
    );
  }
  const critical = target.severity === "critical";
  return (
    <Badge
      className={`text-xxs border-0 gap-1 ${
        critical ? "bg-loss/10 text-loss" : "bg-warning/10 text-warning"
      }`}
    >
      <AlertTriangle size={10} aria-hidden="true" />
      {critical ? "Critical" : "Warning"}
    </Badge>
  );
}

function SeverityCounts({ target }: { target: ReconciliationTargetStatus }) {
  const counts = target.severity_counts;
  const chips: Array<{ label: string; value: number; className: string }> = [
    { label: "critical", value: counts?.critical ?? 0, className: "text-loss" },
    { label: "warning", value: counts?.warning ?? 0, className: "text-warning" },
    { label: "info", value: counts?.info ?? 0, className: "text-text-muted" },
  ];
  const visible = chips.filter((c) => c.value > 0);
  if (visible.length === 0) {
    return <span className="text-xxs text-text-muted">—</span>;
  }
  return (
    <span className="flex items-center gap-2">
      {visible.map((c) => (
        <span key={c.label} className={`text-xxs font-mono tabular-nums ${c.className}`}>
          {c.value} {c.label}
        </span>
      ))}
    </span>
  );
}

// ---------------------------------------------------------------------------
// Expanded latest-report detail
// ---------------------------------------------------------------------------

function DiffList({ report }: { report: ReconciliationReport }) {
  if (report.error) {
    return (
      <p className="text-xxs text-loss">
        Broker fetch failed — broker state unknown: {report.error}
      </p>
    );
  }
  if (report.clean) {
    return (
      <p className="text-xxs text-profit">
        Clean — the broker and FlintTrade agree completely.
      </p>
    );
  }
  return (
    <div className="space-y-2">
      {report.orders_diff.length > 0 && (
        <div>
          <p className="text-xxs uppercase tracking-wider text-text-muted mb-0.5">Orders</p>
          <ul className="space-y-0.5">
            {report.orders_diff.map((d, i) => (
              <li key={`${d.order_id}-${d.discrepancy}-${i}`} className="text-xxs text-text-secondary">
                <span className="font-mono">{d.order_id}</span> {d.symbol} — {d.discrepancy}
                {d.flinttrade_status || d.broker_status
                  ? ` (flinttrade: ${d.flinttrade_status || "—"}, broker: ${d.broker_status || "—"})`
                  : ""}
                {d.detail ? ` · ${d.detail}` : ""}{" "}
                <span className={d.severity === "critical" ? "text-loss" : "text-warning"}>
                  [{d.severity}]
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
      {report.positions_diff.length > 0 && (
        <div>
          <p className="text-xxs uppercase tracking-wider text-text-muted mb-0.5">Positions</p>
          <ul className="space-y-0.5">
            {report.positions_diff.map((d, i) => (
              <li key={`${d.symbol}-${d.exchange}-${d.product}-${i}`} className="text-xxs text-text-secondary">
                <span className="font-mono">{d.symbol}</span> {d.exchange} {d.product} —{" "}
                {d.discrepancy}: flinttrade {d.flinttrade_qty} vs broker {d.broker_qty}{" "}
                <span className="text-loss">[{d.severity}]</span>
              </li>
            ))}
          </ul>
        </div>
      )}
      {report.holdings_diff.length > 0 && (
        <div>
          <p className="text-xxs uppercase tracking-wider text-text-muted mb-0.5">Holdings</p>
          <ul className="space-y-0.5">
            {report.holdings_diff.map((d, i) => (
              <li key={`${d.symbol}-${d.exchange}-${i}`} className="text-xxs text-text-secondary">
                <span className="font-mono">{d.symbol}</span> {d.exchange} — {d.discrepancy}:
                flinttrade {d.flinttrade_qty} vs broker {d.broker_qty}{" "}
                <span className="text-warning">[{d.severity}]</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function ReportDetail({ broker, accountId }: { broker: string; accountId: string }) {
  const { data, isLoading, isError, error } = useReconciliationReports(broker, accountId, 1, true);
  if (isLoading) {
    return (
      <p className="text-xxs text-text-muted flex items-center gap-1">
        <Loader2 size={10} className="animate-spin" aria-hidden="true" /> Loading latest report…
      </p>
    );
  }
  if (isError) {
    return (
      <p className="text-xxs text-loss">
        Could not load the latest report{error instanceof Error ? `: ${error.message}` : ""}
      </p>
    );
  }
  const report = data?.[0];
  if (!report) {
    return <p className="text-xxs text-text-muted">No persisted report for this target yet.</p>;
  }
  return <DiffList report={report} />;
}

// ---------------------------------------------------------------------------
// Widget
// ---------------------------------------------------------------------------

function ReconciliationWidget(_props: WidgetProps) {
  const { data, isLoading, isError, error, refetch, isFetching } = useReconciliationStatus();
  const runMutation = useRunReconciliation();
  const [expandedKey, setExpandedKey] = useState<string | null>(null);

  const targets = data?.targets ?? [];
  const runnerActive = data?.runner_active ?? false;

  const handleRun = () => {
    runMutation.mutate(undefined, {
      onSuccess: (result) => {
        emitNotification({
          category: "system",
          title: "Reconciliation cycle ran",
          body:
            result.count === 0
              ? "No targets were due — each broker reconciles on its own cadence."
              : `Produced ${result.count} report${result.count === 1 ? "" : "s"}.`,
        });
      },
      onError: (err) => {
        emitNotification({
          category: "alert",
          title: "Reconciliation failed",
          body: err instanceof Error ? err.message : "Could not run reconciliation.",
        });
      },
    });
  };

  return (
    <div className="h-full flex flex-col overflow-hidden text-xs bg-surface-base">
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-1.5 border-b border-border-default shrink-0">
        <div className="flex items-center gap-2">
          <Scale size={13} className="text-accent" aria-hidden="true" />
          <span className="text-xxs uppercase tracking-wider text-text-muted font-heading font-semibold">
            Reconciliation
          </span>
          <span
            className={`text-xxs ${runnerActive ? "text-profit" : "text-text-muted"}`}
            title={
              runnerActive
                ? "The background runner is polling active native broker sessions."
                : "The background runner is dormant — no native broker sessions."
            }
          >
            {runnerActive ? "Runner active" : "Runner dormant"}
          </span>
        </div>
        <Button
          size="sm"
          variant="outline"
          onClick={handleRun}
          disabled={runMutation.isPending}
          aria-label="Reconcile now"
          className="h-6 px-2 text-xxs gap-1 border-border-default text-text-secondary hover:text-text-primary transition-colors"
        >
          <RefreshCw size={10} className={runMutation.isPending ? "animate-spin" : ""} />
          {runMutation.isPending ? "Reconciling…" : "Reconcile now"}
        </Button>
      </div>

      {/* Error banner */}
      {isError && (
        <div className="flex items-center gap-2 px-3 py-2 mx-3 mt-2 bg-loss/10 border border-loss/20 rounded-md text-sm text-loss">
          <span className="flex-1">
            Failed to load reconciliation status
            {error instanceof Error ? `: ${error.message}` : ""}
          </span>
          <Button
            variant="link"
            size="sm"
            onClick={() => void refetch()}
            disabled={isFetching}
            className="shrink-0 h-auto p-0 text-xs font-medium text-loss hover:text-loss/80 disabled:opacity-50"
          >
            {isFetching ? "Retrying…" : "Retry"}
          </Button>
        </div>
      )}

      {/* Body */}
      {isLoading ? (
        <div className="flex items-center justify-center flex-1 gap-2 text-text-muted">
          <Loader2 size={14} className="animate-spin" aria-hidden="true" />
          <span className="text-xs">Loading…</span>
        </div>
      ) : targets.length === 0 ? (
        <div className="flex-1 flex flex-col items-center justify-center gap-2 text-center px-4 text-text-muted">
          <Scale size={24} className="text-text-disabled" aria-hidden="true" />
          <span className="text-sm">No reconciliation reports yet</span>
          <span className="text-xxs max-w-72">
            {runnerActive
              ? "The runner is active — the first cycle will appear here shortly."
              : "No native broker sessions active — reconciliation runs once a native adapter is live"}
          </span>
        </div>
      ) : (
        <div className="flex-1 overflow-auto min-h-0">
          <Table>
            <TableHeader className="sticky top-0 bg-surface-card z-10">
              <TableRow className="border-border-default hover:bg-transparent">
                <TableHead className="text-xxs text-text-muted uppercase tracking-wider px-2 py-1 w-6" />
                <TableHead className="text-xxs text-text-muted uppercase tracking-wider px-2 py-1">
                  Broker
                </TableHead>
                <TableHead className="text-xxs text-text-muted uppercase tracking-wider px-2 py-1">
                  Account
                </TableHead>
                <TableHead className="text-xxs text-text-muted uppercase tracking-wider px-2 py-1">
                  Status
                </TableHead>
                <TableHead className="text-xxs text-text-muted uppercase tracking-wider px-2 py-1">
                  Issues
                </TableHead>
                <TableHead className="text-xxs text-text-muted uppercase tracking-wider px-2 py-1">
                  Last run
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {targets.map((target) => {
                const key = `${target.broker}:${target.account_id}`;
                const expanded = expandedKey === key;
                return [
                  <TableRow
                    key={key}
                    className="border-t border-border-subtle hover:bg-surface-hover/50"
                  >
                    <TableCell className="px-2 py-1">
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() => setExpandedKey(expanded ? null : key)}
                        aria-label={`${expanded ? "Hide" : "Show"} latest report for ${target.broker} ${target.account_id}`}
                        aria-expanded={expanded}
                        className="h-5 w-5 p-0 text-text-muted hover:text-text-primary"
                      >
                        {expanded ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
                      </Button>
                    </TableCell>
                    <TableCell className="px-2 py-1 font-mono font-medium whitespace-nowrap">
                      {target.broker}
                    </TableCell>
                    <TableCell className="px-2 py-1 font-mono text-text-secondary whitespace-nowrap">
                      {target.account_id}
                    </TableCell>
                    <TableCell className="px-2 py-1">
                      <StatusBadge target={target} />
                    </TableCell>
                    <TableCell className="px-2 py-1">
                      <SeverityCounts target={target} />
                    </TableCell>
                    <TableCell className="px-2 py-1 text-text-muted whitespace-nowrap">
                      {formatReportTime(target.last_report_at)}
                    </TableCell>
                  </TableRow>,
                  expanded ? (
                    <TableRow key={`${key}-detail`} className="border-t border-border-subtle">
                      <TableCell colSpan={6} className="px-4 py-2 bg-surface-card/50">
                        <ReportDetail broker={target.broker} accountId={target.account_id} />
                      </TableCell>
                    </TableRow>
                  ) : null,
                ];
              })}
            </TableBody>
          </Table>
        </div>
      )}
    </div>
  );
}

export default memo(ReconciliationWidget);
