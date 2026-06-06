/**
 * HistoricalDownloadPanel — start and monitor bulk OHLCV downloads.
 *
 * Drives the backend download-job manager:
 *   POST /ft-api/v1/historify/download           → starts a background job
 *   GET  /ft-api/v1/historify/download/status?... → live progress + ETA + safety
 *
 * Shows a real progress bar, the time-remaining estimate, and the disk-safety
 * state reported by the backend. All data is live job state — nothing fabricated.
 */

import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Download, AlertTriangle, CheckCircle2, Loader2, HardDrive } from "lucide-react";
import { Button } from "@/components/ui/button";
import { SectionTitle } from "./shared";

const BASE = "/ft-api/v1/historify";

interface DownloadJob {
  job_id: string;
  status: "queued" | "running" | "done" | "error" | "refused" | "aborted";
  total: number;
  completed: number;
  progress_pct: number;
  eta_seconds: number | null;
  free_disk_mb: number | null;
  error: string | null;
  message: string;
}

async function startDownload(): Promise<DownloadJob> {
  const res = await fetch(`${BASE}/download`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({}),
  });
  const json = (await res.json().catch(() => null)) as { data?: DownloadJob; message?: string } | null;
  // 202 (started) and 507 (refused) both return a job snapshot in `data`.
  if (json?.data) return json.data;
  throw new Error(json?.message ?? `Download failed (${res.status})`);
}

async function fetchStatus(jobId: string): Promise<DownloadJob> {
  const res = await fetch(`${BASE}/download/status?job_id=${encodeURIComponent(jobId)}`);
  const json = (await res.json()) as { data: DownloadJob };
  return json.data;
}

function formatEta(seconds: number | null): string {
  if (seconds == null) return "—";
  if (seconds <= 0) return "0s";
  if (seconds < 60) return `${Math.round(seconds)}s`;
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  return `${m}m ${s}s`;
}

export function HistoricalDownloadPanel() {
  const [jobId, setJobId] = useState<string | null>(null);

  const startMutation = useMutation({
    mutationFn: startDownload,
    onSuccess: (job) => setJobId(job.job_id),
  });

  const { data: job } = useQuery({
    queryKey: ["historify", "status", jobId],
    queryFn: () => fetchStatus(jobId as string),
    enabled: !!jobId,
    refetchInterval: (q) => {
      const s = q.state.data?.status;
      return s === "running" || s === "queued" ? 1000 : false;
    },
    initialData: () => startMutation.data,
  });

  const active = job ?? startMutation.data;
  const isRunning = active?.status === "running" || active?.status === "queued";

  return (
    <div className="space-y-3">
      <SectionTitle>Historical Download</SectionTitle>

      <div className="p-3 rounded-lg bg-surface-card border border-border-default space-y-3">
        <div className="flex items-center justify-between gap-3">
          <p className="text-xs text-text-muted leading-snug">
            Download the last 30 days of OHLCV for every enabled watchlist symbol.
            Runs in the background and persists to local storage.
          </p>
          <Button
            size="sm"
            variant="outline"
            onClick={() => startMutation.mutate()}
            disabled={startMutation.isPending || isRunning}
            className="shrink-0 gap-1.5"
          >
            {startMutation.isPending || isRunning ? (
              <Loader2 size={13} className="animate-spin" />
            ) : (
              <Download size={13} />
            )}
            {isRunning ? "Downloading…" : "Download 30d"}
          </Button>
        </div>

        {startMutation.isError && (
          <p role="alert" className="text-xs text-loss">
            {startMutation.error instanceof Error ? startMutation.error.message : "Failed to start"}
          </p>
        )}

        {/* refused (start-time) and aborted (mid-run disk fill) both surface a
            clear disk-safety message instead of a progress bar. */}
        {active && (active.status === "refused" || active.status === "aborted") && (
          <div className="flex items-start gap-2 rounded border border-warning/30 bg-warning/10 px-3 py-2">
            <AlertTriangle size={14} className="text-warning flex-none mt-0.5" />
            <p className="text-xs text-warning">{active.message}</p>
          </div>
        )}

        {active && active.status !== "refused" && active.status !== "aborted" && (
          <div className="space-y-2">
            {/* Progress bar */}
            <div className="h-2 w-full overflow-hidden rounded-full bg-surface-base">
              <div
                className={
                  active.status === "error"
                    ? "h-full bg-loss transition-all"
                    : active.status === "done"
                      ? "h-full bg-profit transition-all"
                      : "h-full bg-accent transition-all"
                }
                style={{ width: `${active.progress_pct}%` }}
                role="progressbar"
                aria-valuenow={active.progress_pct}
                aria-valuemin={0}
                aria-valuemax={100}
                aria-label="Download progress"
              />
            </div>
            <div className="flex flex-wrap items-center justify-between gap-2 text-xxs text-text-muted">
              <span className="font-mono">
                {active.completed}/{active.total} · {active.progress_pct}%
              </span>
              {isRunning && <span>ETA {formatEta(active.eta_seconds)}</span>}
              {active.status === "done" && (
                <span className="flex items-center gap-1 text-profit">
                  <CheckCircle2 size={11} /> Complete
                </span>
              )}
              {active.status === "error" && (
                <span className="text-loss">{active.error ?? "Failed"}</span>
              )}
              {active.free_disk_mb != null && active.free_disk_mb >= 0 && (
                <span className="flex items-center gap-1">
                  <HardDrive size={11} /> {Math.round(active.free_disk_mb)} MB free
                </span>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
