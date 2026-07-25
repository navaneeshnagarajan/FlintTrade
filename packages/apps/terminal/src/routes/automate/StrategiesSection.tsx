/**
 * StrategiesSection — uploaded Python strategy management.
 *
 * Features:
 * - List of uploaded .py strategies with status (Running / Stopped / Crashed)
 * - Upload button (file input restricted to .py files)
 * - Start / Stop buttons per strategy
 * - Expandable log viewer panel (SSE stream of strategy output)
 *
 * API calls via ftApi:
 *   GET  /ft-api/api/v1/strategies/uploaded
 *   POST /ft-api/api/v1/strategies/upload        (multipart)
 *   POST /ft-api/api/v1/strategies/uploaded/:id/start
 *   POST /ft-api/api/v1/strategies/uploaded/:id/stop
 *   GET  /ft-api/api/v1/strategies/uploaded/:id/logs
 */

import { useState, useCallback, useRef } from "react";
import {
  Upload,
  Play,
  Square,
  ChevronDown,
  ChevronRight,
  Loader2,
  RefreshCw,
  FileCode2,
} from "lucide-react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
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
import { StaggeredList } from "@/components/motion/StaggeredList";
import {
  getUploadedStrategies,
  uploadStrategy,
  startUploadedStrategy,
  stopUploadedStrategy,
  getStrategyLogs,
  type UploadedStrategy,
  type StrategyLogEntry,
} from "@/services/ftApi";
import { InlineToast, useInlineToast } from "./shared";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";

// ---------------------------------------------------------------------------
// Status badge
// ---------------------------------------------------------------------------

function StrategyStatusBadge({ status }: { status: UploadedStrategy["status"] }) {
  switch (status) {
    case "running":
      return (
        <Badge className="text-xs bg-profit/10 text-profit border-0 gap-1">
          <span className="w-1.5 h-1.5 rounded-full bg-profit animate-pulse inline-block" />
          Running
        </Badge>
      );
    case "stopped":
      return (
        <Badge className="text-xs bg-text-muted/10 text-text-muted border-0">
          Stopped
        </Badge>
      );
    case "crashed":
      return (
        <Badge className="text-xs bg-loss/10 text-loss border-0">
          Crashed
        </Badge>
      );
    case "uploading":
      return (
        <Badge className="text-xs bg-accent/10 text-accent border-0 gap-1">
          <Loader2 size={10} className="animate-spin" />
          Uploading
        </Badge>
      );
    default:
      return (
        <Badge className="text-xs bg-text-muted/10 text-text-muted border-0">
          {status}
        </Badge>
      );
  }
}

// ---------------------------------------------------------------------------
// Log level colour
// ---------------------------------------------------------------------------

function logLevelClass(level: StrategyLogEntry["level"]): string {
  switch (level) {
    case "ERROR":
      return "text-loss";
    case "WARNING":
      return "text-amber-400";
    case "DEBUG":
      return "text-text-muted";
    default:
      return "text-text-secondary";
  }
}

// ---------------------------------------------------------------------------
// Strategy row with expandable log panel
// ---------------------------------------------------------------------------

interface StrategyRowProps {
  strategy: UploadedStrategy;
  onStart: (id: string) => void;
  onStop: (id: string) => void;
  actionPending: boolean;
}

function StrategyRow({ strategy, onStart, onStop, actionPending }: StrategyRowProps) {
  const [logsOpen, setLogsOpen] = useState(false);

  const { data: logs, isLoading: logsLoading, refetch: refetchLogs } = useQuery({
    queryKey: ["strategyLogs", strategy.id],
    queryFn: () => getStrategyLogs(strategy.id),
    enabled: logsOpen,
    refetchInterval: logsOpen && strategy.status === "running" ? 3_000 : false,
  });

  const isRunning = strategy.status === "running";
  const canStart = strategy.status === "stopped" || strategy.status === "crashed";

  return (
    <>
      <TableRow className="border-border-default hover:bg-surface-base">
        <TableCell className="py-2 w-5">
          <button
            onClick={() => setLogsOpen((v) => !v)}
            aria-label={logsOpen ? "Collapse logs" : "Expand logs"}
            className="text-text-muted hover:text-text-primary transition-colors"
          >
            {logsOpen ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
          </button>
        </TableCell>
        <TableCell className="py-2">
          <div className="flex items-center gap-2">
            <FileCode2 size={13} className="text-accent shrink-0" />
            <div>
              <p className="text-xs font-medium text-text-primary">{strategy.name}</p>
              <p className="text-xxs text-text-muted font-mono">{strategy.filename}</p>
            </div>
          </div>
        </TableCell>
        <TableCell className="py-2">
          <StrategyStatusBadge status={strategy.status} />
        </TableCell>
        <TableCell className="py-2 text-xxs text-text-muted font-mono">
          {strategy.started_at
            ? new Date(strategy.started_at).toLocaleTimeString("en-IN", {
                timeZone: "Asia/Kolkata",
                hour: "2-digit",
                minute: "2-digit",
                second: "2-digit",
              })
            : "—"}
        </TableCell>
        <TableCell className="py-2">
          <div className="flex items-center gap-1">
            {canStart && (
              <Button
                size="sm"
                variant="ghost"
                disabled={actionPending}
                onClick={() => onStart(strategy.id)}
                aria-label={`Start ${strategy.name}`}
                className="h-6 w-6 p-0 text-profit hover:bg-profit/10"
              >
                <Play size={11} />
              </Button>
            )}
            {isRunning && (
              <Button
                size="sm"
                variant="ghost"
                disabled={actionPending}
                onClick={() => onStop(strategy.id)}
                aria-label={`Stop ${strategy.name}`}
                className="h-6 w-6 p-0 text-loss hover:bg-loss/10"
              >
                <Square size={11} />
              </Button>
            )}
          </div>
        </TableCell>
      </TableRow>

      {/* Expandable log viewer */}
      {logsOpen && (
        <TableRow className="border-border-default">
          <TableCell colSpan={5} className="py-0 px-3 pb-3">
            <div className="rounded-lg border border-border-default bg-surface-base overflow-hidden">
              <div className="flex items-center justify-between px-3 py-1.5 border-b border-border-default">
                <span className="text-xxs text-text-muted font-medium uppercase tracking-wider">
                  Logs — {strategy.name}
                </span>
                <button
                  onClick={() => void refetchLogs()}
                  disabled={logsLoading}
                  aria-label="Refresh logs"
                  className="text-text-muted hover:text-text-primary transition-colors"
                >
                  <RefreshCw size={11} className={logsLoading ? "animate-spin" : ""} />
                </button>
              </div>
              <ScrollArea className="h-40">
                <div className="p-3 space-y-0.5 font-mono text-xxs">
                  {logsLoading && (
                    <div className="flex items-center gap-2 text-text-muted py-4 justify-center">
                      <Loader2 size={12} className="animate-spin" />
                      Loading logs…
                    </div>
                  )}
                  {!logsLoading && (!logs || logs.length === 0) && (
                    <p className="text-text-muted text-center py-4">
                      No log entries yet.
                    </p>
                  )}
                  {logs?.map((entry, i) => (
                    <div key={`${entry.timestamp}-${i}`} className="flex items-start gap-2 leading-relaxed">
                      <span className="text-text-disabled shrink-0 tabular-nums">
                        {new Date(entry.timestamp).toLocaleTimeString("en-IN", {
                          timeZone: "Asia/Kolkata",
                          hour: "2-digit",
                          minute: "2-digit",
                          second: "2-digit",
                        })}
                      </span>
                      <span
                        className={`shrink-0 w-12 font-semibold ${logLevelClass(entry.level)}`}
                      >
                        {entry.level}
                      </span>
                      <span className="text-text-secondary break-all">{entry.message}</span>
                    </div>
                  ))}
                </div>
              </ScrollArea>
            </div>
          </TableCell>
        </TableRow>
      )}
    </>
  );
}

// ---------------------------------------------------------------------------
// Main section
// ---------------------------------------------------------------------------

export default function StrategiesSection() {
  const queryClient = useQueryClient();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const { toast, setToast, dismissToast } = useInlineToast();
  // Starting an uploaded strategy hands an automated process the order path.
  // That is a larger side effect than arming the account mirror, which already
  // confirms, so it gets the same treatment.
  const [pendingStart, setPendingStart] = useState<UploadedStrategy | null>(null);

  const { data: strategies, isLoading, isError } = useQuery({
    queryKey: ["uploadedStrategies"],
    queryFn: getUploadedStrategies,
    refetchInterval: 10_000,
  });

  const uploadMutation = useMutation({
    mutationFn: (file: File) => uploadStrategy(file),
    onSuccess: (uploaded) => {
      void queryClient.invalidateQueries({ queryKey: ["uploadedStrategies"] });
      setToast({ msg: `Uploaded: ${uploaded.filename}`, variant: "success" });
    },
    onError: (err: Error) => {
      setToast({ msg: err.message ?? "Upload failed", variant: "error" });
    },
  });

  const startMutation = useMutation({
    mutationFn: (id: string) => startUploadedStrategy(id),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["uploadedStrategies"] });
      setToast({ msg: "Strategy started", variant: "success" });
    },
    onError: (err: Error) => {
      setToast({ msg: err.message ?? "Failed to start strategy", variant: "error" });
    },
  });

  const stopMutation = useMutation({
    mutationFn: (id: string) => stopUploadedStrategy(id),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["uploadedStrategies"] });
      setToast({ msg: "Strategy stopped", variant: "success" });
    },
    onError: (err: Error) => {
      setToast({ msg: err.message ?? "Failed to stop strategy", variant: "error" });
    },
  });

  const handleFileChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0];
      if (!file) return;
      if (!file.name.endsWith(".py")) {
        setToast({ msg: "Only .py files are allowed", variant: "error" });
        return;
      }
      uploadMutation.mutate(file);
      // Reset so same file can be re-uploaded
      e.target.value = "";
    },
    [uploadMutation, setToast],
  );

  const runningCount = (strategies ?? []).filter(
    (s) => s.status === "running",
  ).length;

  const actionPending = startMutation.isPending || stopMutation.isPending;

  return (
    <div className="space-y-4">
      <StaggeredList className="space-y-4">

        {/* Overview */}
        <GlassCard className="p-6">
          <div className="flex items-center justify-between mb-4">
            <div>
              <h3 className="font-heading font-semibold text-lg text-text-primary">
                Python Strategies
              </h3>
              <p className="text-sm text-text-secondary leading-relaxed mt-1">
                Upload and run custom Python trading strategies on the FlintTrade
                backend. Each strategy runs as an isolated process with access to
                live market data.
              </p>
            </div>
            <div className="flex items-center gap-3 shrink-0">
              {runningCount > 0 && (
                <Badge className="text-xs bg-profit/10 text-profit border-0 gap-1">
                  <span className="w-1.5 h-1.5 rounded-full bg-profit animate-pulse inline-block" />
                  {runningCount} running
                </Badge>
              )}
              <Button
                size="sm"
                variant="outline"
                disabled={uploadMutation.isPending}
                onClick={() => fileInputRef.current?.click()}
                className="h-7 px-3 gap-1.5 border-border-default text-text-primary hover:text-accent hover:border-accent text-xs"
              >
                {uploadMutation.isPending ? (
                  <Loader2 size={12} className="animate-spin" />
                ) : (
                  <Upload size={12} />
                )}
                Upload Strategy
              </Button>
              {/* Hidden file input */}
              <input
                ref={fileInputRef}
                type="file"
                accept=".py"
                className="hidden"
                onChange={handleFileChange}
                aria-label="Upload Python strategy file"
              />
            </div>
          </div>

          <div className="grid grid-cols-3 gap-3 mb-0">
            <div className="bg-surface-base border border-border-default rounded-lg p-4">
              <p className="text-xs text-text-muted mb-1">Total</p>
              <p className="text-2xl font-mono font-bold text-text-primary">
                {strategies?.length ?? 0}
              </p>
            </div>
            <div className="bg-surface-base border border-border-default rounded-lg p-4">
              <p className="text-xs text-text-muted mb-1">Running</p>
              <p className="text-2xl font-mono font-bold text-profit">
                {runningCount}
              </p>
            </div>
            <div className="bg-surface-base border border-border-default rounded-lg p-4">
              <p className="text-xs text-text-muted mb-1">Crashed</p>
              <p className="text-2xl font-mono font-bold text-loss">
                {(strategies ?? []).filter((s) => s.status === "crashed").length}
              </p>
            </div>
          </div>
        </GlassCard>

        {/* Strategy table */}
        <GlassCard className="p-6">
          <h3 className="font-heading font-semibold text-sm text-text-primary mb-3">
            Uploaded Strategies
          </h3>

          {toast && (
            <div className="mb-3">
              <InlineToast
                message={toast.msg}
                variant={toast.variant}
                onDismiss={dismissToast}
              />
            </div>
          )}

          {isLoading && (
            <div className="flex items-center justify-center py-10">
              <Loader2 size={18} className="animate-spin text-text-muted" />
            </div>
          )}

          {isError && (
            <p className="text-xs text-loss text-center py-6">
              Failed to load strategies. Backend may be offline.
            </p>
          )}

          {!isLoading && !isError && (strategies ?? []).length === 0 && (
            <div className="flex flex-col items-center gap-2 py-10 text-center">
              <FileCode2 size={24} className="text-text-muted" />
              <p className="text-xs text-text-muted">
                No strategies uploaded yet.
              </p>
              <p className="text-xxs text-text-muted">
                Click "Upload Strategy" above to add a .py file.
              </p>
            </div>
          )}

          {!isLoading && !isError && (strategies ?? []).length > 0 && (
            <Table>
              <TableHeader>
                <TableRow className="border-border-default hover:bg-transparent">
                  <TableHead className="w-5" />
                  <TableHead className="text-xs text-text-muted font-medium">
                    Strategy
                  </TableHead>
                  <TableHead className="text-xs text-text-muted font-medium">
                    Status
                  </TableHead>
                  <TableHead className="text-xs text-text-muted font-medium">
                    Started
                  </TableHead>
                  <TableHead className="text-xs text-text-muted font-medium w-16">
                    Actions
                  </TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {(strategies ?? []).map((strategy) => (
                  <StrategyRow
                    key={strategy.id}
                    strategy={strategy}
                    onStart={() => setPendingStart(strategy)}
                    onStop={(id) => stopMutation.mutate(id)}
                    actionPending={actionPending}
                  />
                ))}
              </TableBody>
            </Table>
          )}
        </GlassCard>

      </StaggeredList>

      {/* Starting a strategy runs operator-supplied Python that can place
          orders on its own. The confirmation names the file, because the
          strategy list shows display names and two uploads can share one. */}
      <AlertDialog
        open={pendingStart != null}
        onOpenChange={(open) => { if (!open) setPendingStart(null); }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Start {pendingStart?.name}?</AlertDialogTitle>
            <AlertDialogDescription>
              <strong>{pendingStart?.filename}</strong> will run continuously and
              may place orders without further prompting. Every order it sends
              still passes the full safety gate, but nothing else asks you
              first. Stop it from this table when you are done.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => {
                if (pendingStart) startMutation.mutate(pendingStart.id);
                setPendingStart(null);
              }}
            >
              Start strategy
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
