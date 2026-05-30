/**
 * LogsSection — Local audit log viewer.
 * Paginated by date, with load-more for large days.
 */

import { useState, useEffect } from "react";
import { RefreshCw, Loader2 } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import { GlassCard } from "@/components/ui/GlassCard";
import { getAuditLogs, type AuditLog } from "@/services/ftApi";
import { VerdictBadge, verdictClass } from "./shared";

const PAGE_SIZE = 50;

function formatTs(ts: string): string {
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
}

export default function LogsSection() {
  const today = new Date().toISOString().slice(0, 10);
  const [date, setDate]       = useState(today);
  const [offset, setOffset]   = useState(0);
  const [allLogs, setAllLogs] = useState<AuditLog[]>([]);
  const [total, setTotal]     = useState(0);

  const { data, isFetching, isError, refetch } = useQuery({
    queryKey: ["auditLogs", date, offset],
    queryFn: () => getAuditLogs(date, PAGE_SIZE, offset),
  });

  useEffect(() => {
    if (!data) return;
    if (offset === 0) {
      setAllLogs(data.logs);
    } else {
      setAllLogs((prev) => [...prev, ...data.logs]);
    }
    setTotal(data.total);
  }, [data, offset]);

  const handleDateChange = (newDate: string) => {
    setDate(newDate);
    setOffset(0);
    setAllLogs([]);
    setTotal(0);
  };

  const hasMore = allLogs.length < total;

  return (
    <div className="space-y-4">
      <GlassCard className="p-6">
        <div className="flex items-center justify-between mb-4 gap-4">
          <div>
            <h3 className="font-heading font-semibold text-lg text-text-primary">Execution Logs</h3>
            <p className="text-sm text-text-secondary mt-0.5">
              Append-only audit trail. Every trigger, condition, and order action is recorded.
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
                        {log.exchange ? <span className="text-text-muted"> · {log.exchange}</span> : null}
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
                  onClick={() => setOffset((prev) => prev + PAGE_SIZE)}
                  disabled={isFetching}
                  className="h-8 px-6 text-xs border-border-default text-text-secondary hover:text-text-primary"
                >
                  {isFetching ? <Loader2 size={12} className="animate-spin mr-1.5" /> : null}
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
