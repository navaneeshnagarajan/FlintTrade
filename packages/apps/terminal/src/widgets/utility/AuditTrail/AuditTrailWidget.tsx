/**
 * AuditTrailWidget — Append-only user-action audit log for FlintTrade.
 *
 * Features:
 *   - Scrollable table of user actions: orders, position changes, settings, logins
 *   - Columns: timestamp (IST), action type, details, user, IP
 *   - Filter by action type and date range
 *   - Export to CSV
 *   - retention is operator-controlled (kept on disk under ~/.flinttrade)
 *   - Sample data in explore mode; live data via ft-api in connected mode
 */

import { useState, useMemo, useEffect, useCallback, memo } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  ScrollText,
  Download,
  RefreshCw,
  Loader2,
  AlertCircle,
} from "lucide-react";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { getActivityLog } from "@/services/ftApi";
import type { ActivityEntry } from "@/services/ftApi";
import { SAMPLE_AUDIT_ENTRIES, ACTION_TYPES } from "./sampleData";
import { useBrokerConnected } from "@/hooks/useBrokerConnected";
import { useTrackBehavior } from "@/hooks/useTrackBehavior";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const ACTION_BADGE: Record<string, string> = {
  order_placed:    "bg-profit/10 text-profit border-profit/20",
  order_cancelled: "bg-loss/10 text-loss border-loss/20",
  order_modified:  "bg-accent/10 text-accent border-accent/20",
  position_closed: "bg-text-muted/15 text-text-secondary border-border-subtle",
  settings_changed:"bg-accent/10 text-accent border-accent/20",
  login:           "bg-surface-hover text-text-secondary border-border-subtle",
  logout:          "bg-surface-hover text-text-muted border-border-subtle",
};

const ACTION_LABELS: Record<string, string> = {
  order_placed:    "Order Placed",
  order_cancelled: "Order Cancelled",
  order_modified:  "Order Modified",
  position_closed: "Position Closed",
  settings_changed:"Settings Changed",
  login:           "Login",
  logout:          "Logout",
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatTimestamp(iso: string): string {
  return new Date(iso).toLocaleString("en-IN", {
    timeZone: "Asia/Kolkata",
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  });
}

function exportCsv(entries: ActivityEntry[]) {
  const header = "Timestamp,Action,Details,User,IP\n";
  const rows = entries
    .map((e) => {
      const ts = formatTimestamp(e.timestamp);
      const action = ACTION_LABELS[e.action] ?? e.action;
      const details = `"${e.details.replace(/"/g, '""')}"`;
      return `${ts},${action},${details},${e.user},${e.ip}`;
    })
    .join("\n");
  const blob = new Blob([header + rows], { type: "text/csv" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `flinttrade-audit-${new Date().toISOString().slice(0, 10)}.csv`;
  a.click();
  URL.revokeObjectURL(url);
}

// ---------------------------------------------------------------------------
// Audit row
// ---------------------------------------------------------------------------

interface AuditRowProps {
  entry: ActivityEntry;
}

function AuditRow({ entry }: AuditRowProps) {
  const badgeClass = ACTION_BADGE[entry.action] ?? "bg-surface-hover text-text-secondary border-border-subtle";
  const label = ACTION_LABELS[entry.action] ?? entry.action;

  return (
    <tr className="border-b border-border-subtle hover:bg-surface-hover/40 transition-colors">
      <td className="px-2 py-1.5 whitespace-nowrap">
        <span className="text-xxs font-mono tabular-nums text-text-secondary">
          {formatTimestamp(entry.timestamp)}
        </span>
      </td>
      <td className="px-2 py-1.5 whitespace-nowrap">
        <span className={cn("text-xxs px-1.5 py-px rounded border font-mono", badgeClass)}>
          {label}
        </span>
      </td>
      <td className="px-2 py-1.5 max-w-[240px] truncate">
        <span className="text-xs text-text-primary" title={entry.details}>
          {entry.details}
        </span>
      </td>
      <td className="px-2 py-1.5 whitespace-nowrap">
        <span className="text-xs font-mono text-text-secondary">{entry.user}</span>
      </td>
      <td className="px-2 py-1.5 whitespace-nowrap">
        <span className="text-xxs font-mono text-text-muted">{entry.ip || "—"}</span>
      </td>
    </tr>
  );
}

// ---------------------------------------------------------------------------
// Main widget
// ---------------------------------------------------------------------------

function AuditTrailWidget() {
  const track = useTrackBehavior();
  const isConnected = useBrokerConnected();

  const [actionFilter, setActionFilter] = useState<string>("all");
  const [sinceDate, setSinceDate] = useState<string>("");

  useEffect(() => {
    track("trade", "widget_view_audit_trail");
  }, [track]);

  const {
    data: liveData,
    isLoading,
    isError,
    error,
    isFetching,
    refetch,
  } = useQuery({
    queryKey: ["activityLog", actionFilter, sinceDate],
    queryFn: () =>
      getActivityLog({
        action: actionFilter !== "all" ? actionFilter : undefined,
        since: sinceDate || undefined,
        limit: 200,
      }),
    enabled: isConnected,
    staleTime: 30_000,
  });

  const rawEntries: ActivityEntry[] = isConnected
    ? (liveData?.entries ?? SAMPLE_AUDIT_ENTRIES)
    : SAMPLE_AUDIT_ENTRIES;

  const filtered = useMemo(() => {
    let entries = rawEntries;
    if (actionFilter !== "all") {
      entries = entries.filter((e) => e.action === actionFilter);
    }
    if (sinceDate) {
      const since = new Date(sinceDate).getTime();
      entries = entries.filter((e) => new Date(e.timestamp).getTime() >= since);
    }
    return entries;
  }, [rawEntries, actionFilter, sinceDate]);

  const handleExport = useCallback(() => {
    exportCsv(filtered);
    track("trade", "audit_trail_export_csv");
  }, [filtered, track]);

  return (
    <div className="h-full flex flex-col bg-surface-base overflow-hidden">
      {/* Header */}
      <div className="flex-none flex items-center gap-2 px-3 py-2 bg-surface-card border-b border-border-default">
        <ScrollText size={13} className="text-text-muted" aria-hidden="true" />
        <span className="text-xs font-medium text-text-primary">Audit Trail</span>
        <span className="text-xxs text-text-muted px-1.5 py-px rounded bg-surface-hover border border-border-subtle">
          Audit log
        </span>
        <div className="flex-1" />
        <Button
          variant="outline"
          size="sm"
          onClick={handleExport}
          className="h-5 px-2 text-xxs text-text-muted border-border-subtle hover:text-text-primary"
          aria-label="Export audit log to CSV"
        >
          <Download size={10} aria-hidden="true" />
          CSV
        </Button>
        {isConnected && (
          <Button
            variant="ghost"
            size="sm"
            onClick={() => void refetch()}
            disabled={isFetching}
            className="h-5 w-5 p-0 text-text-muted hover:text-text-primary disabled:opacity-40"
            aria-label="Refresh audit log"
          >
            <RefreshCw size={11} className={isFetching ? "animate-spin" : ""} aria-hidden="true" />
          </Button>
        )}
      </div>

      {/* Filters */}
      <div className="flex-none flex items-center gap-2 px-2 py-1.5 border-b border-border-subtle bg-surface-elevated">
        <Select value={actionFilter} onValueChange={setActionFilter}>
          <SelectTrigger className="h-6 w-36 text-xxs" aria-label="Filter by action type">
            <SelectValue placeholder="All actions" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all" className="text-xs">All Actions</SelectItem>
            {ACTION_TYPES.map((a) => (
              <SelectItem key={a} value={a} className="text-xs">
                {ACTION_LABELS[a] ?? a}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Input
          type="date"
          value={sinceDate}
          onChange={(e) => setSinceDate(e.target.value)}
          className="h-6 w-36 text-xxs"
          aria-label="Filter from date"
        />
        {(actionFilter !== "all" || sinceDate) && (
          <Button
            variant="ghost"
            size="sm"
            className="h-6 px-2 text-xxs text-text-muted"
            onClick={() => { setActionFilter("all"); setSinceDate(""); }}
          >
            Clear
          </Button>
        )}
        <span className="ml-auto text-xxs text-text-muted tabular-nums">
          {filtered.length} entries
        </span>
      </div>

      {/* Error */}
      {isError && (
        <div className="flex-none flex items-center gap-2 px-2 py-1 bg-loss/10 border-b border-loss/20 text-loss text-xs">
          <AlertCircle size={11} aria-hidden="true" />
          <span>{(error as Error)?.message ?? "Failed to load audit log"}</span>
        </div>
      )}

      {/* Loading */}
      {isConnected && isLoading && (
        <div className="flex-1 flex items-center justify-center gap-2 text-text-muted text-sm">
          <Loader2 size={14} className="animate-spin" aria-hidden="true" />
          Loading audit log...
        </div>
      )}

      {/* Table */}
      {!isLoading && (
        <div className="flex-1 overflow-auto">
          <table className="w-full border-collapse" aria-label="User action audit trail">
            <thead>
              <tr className="border-b border-border-default sticky top-0 bg-surface-card z-10">
                <th className="px-2 py-1.5 text-xxs font-medium uppercase tracking-wide text-text-muted text-left whitespace-nowrap">Timestamp (IST)</th>
                <th className="px-2 py-1.5 text-xxs font-medium uppercase tracking-wide text-text-muted text-left whitespace-nowrap">Action</th>
                <th className="px-2 py-1.5 text-xxs font-medium uppercase tracking-wide text-text-muted text-left">Details</th>
                <th className="px-2 py-1.5 text-xxs font-medium uppercase tracking-wide text-text-muted text-left">User</th>
                <th className="px-2 py-1.5 text-xxs font-medium uppercase tracking-wide text-text-muted text-left">IP</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((entry) => (
                <AuditRow key={entry.id} entry={entry} />
              ))}
            </tbody>
          </table>

          {filtered.length === 0 && !isLoading && (
            <div className="flex items-center justify-center py-10 text-text-muted text-sm">
              No audit entries match the current filters.
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default memo(AuditTrailWidget);
