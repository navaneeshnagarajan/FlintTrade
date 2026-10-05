/**
 * CronSection — Schedules tab.
 * Lists all registered cron jobs with pause/resume controls.
 *
 * Explore (FT-AUTO-004): the global sample banner owns disclosure. Seeded or
 * leaked jobs show Sample/Demo (muted) — never a production-Active badge —
 * and Pause is disabled. Practice / Live keep Pause / Resume.
 */

import { useState } from "react";
import { RefreshCw, Loader2, Play, Pause } from "lucide-react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { GlassCard } from "@/components/ui/GlassCard";
import { StaggeredList } from "@/components/motion/StaggeredList";
import {
  getCronJobs,
  pauseCronJob,
  resumeCronJob,
  type CronJob,
} from "@/services/ftApi";
import { useModeStore } from "@/stores/modeStore";
import {
  SAMPLE_SCHEDULE_PAUSE_UNAVAILABLE,
  exploreScheduleDisplayStatus,
  isExploreScheduleControlGated,
  resolveExploreScheduleJobs,
} from "./exploreScheduleGate";
import { StatusDot, StatusBadge } from "./shared";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

// These identifiers come from CronManager.DEFAULT_JOBS. Unknown custom jobs
// remain visible; this changes presentation only, never the scheduler or API IDs.
const SYSTEM_JOBS = new Set([
  "health_check_job", "health_check", "eod_logout_job", "backup",
  "db_optimise_job", "tick_retention_job", "webhook_nonce_gc_job",
]);

const JOB_LABELS: Record<string, string> = {
  health_check_job: "Broker session check",
  health_check: "Connection health check",
  square_off_warning_job: "Square-off warning",
  eod_logout_job: "End-of-day logout",
  backup: "Workspace backup",
  post_market_analysis: "Post-market analysis",
  mcx_close_check: "MCX closing position check",
  db_optimise_job: "Database optimisation",
  tick_retention_job: "Tick data cleanup",
  overnight_optimise_job: "Overnight strategy optimisation",
  eod_sync_job: "End-of-day data sync",
  webhook_nonce_gc_job: "Webhook replay protection cleanup",
  "pre-market-screener": "Pre-market screener",
  "eod-position-snapshot": "End-of-day position snapshot",
};

function jobLabel(name: string): string {
  if (Object.hasOwn(JOB_LABELS, name)) return JOB_LABELS[name]!;
  const words = name.replace(/[_-]job$/, "").replace(/[_-]+/g, " ").trim();
  return words ? words[0]!.toUpperCase() + words.slice(1) : name;
}

function formatLastRun(val: string | null): string {
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
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function CronSection() {
  const queryClient = useQueryClient();
  const mode = useModeStore((state) => state.mode);
  const pauseGated = isExploreScheduleControlGated(mode);
  const [showSystemJobs, setShowSystemJobs] = useState(false);
  const [pendingJob, setPendingJob] = useState<string | null>(null);

  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ["cronJobs"],
    queryFn: getCronJobs,
  });

  const apiJobs: CronJob[] = data?.jobs ?? [];
  const jobs: CronJob[] = pauseGated
    ? resolveExploreScheduleJobs(apiJobs, isLoading)
    : apiJobs;
  const visibleJobs = jobs.filter((job) => showSystemJobs || !SYSTEM_JOBS.has(job.name));

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
    if (pauseGated) return;
    if (job.status.toLowerCase() === "paused") {
      resumeMutation.mutate(job.name);
    } else {
      pauseMutation.mutate(job.name);
    }
  };

  return (
    <div className="space-y-4" data-tour-target="cron-manager">
      <GlassCard className="p-6">
        <div className="flex items-center justify-between mb-4">
          <div>
            <h3 className="font-heading font-semibold text-lg text-text-primary">Schedules</h3>
            <p className="text-sm text-text-secondary mt-0.5">
              Your automation schedules. Pause or resume individual jobs.
            </p>
          </div>
          <Button
            size="sm"
            variant="ghost"
            aria-label="Refresh schedules"
            onClick={() => void refetch()}
            disabled={isLoading}
            className="h-7 w-7 p-0 text-text-muted hover:text-text-primary"
          >
            <RefreshCw size={13} className={isLoading ? "animate-spin" : ""} />
          </Button>
        </div>

        <label className="mb-4 flex items-center gap-2 text-xs text-text-secondary">
          <input
            type="checkbox"
            checked={showSystemJobs}
            onChange={(event) => setShowSystemJobs(event.target.checked)}
            className="accent-accent"
          />
          Show system jobs
        </label>

        {isLoading && (
          <div className="flex items-center justify-center py-10">
            <Loader2 size={18} className="animate-spin text-text-muted" />
          </div>
        )}

        {!pauseGated && isError && (
          <p className="text-xs text-loss text-center py-6">
            Could not load schedules. The backend may be offline.
          </p>
        )}

        {!isLoading && !isError && !pauseGated && jobs.length === 0 && (
          <p className="text-xs text-text-muted text-center py-8">
            No schedules registered. Add schedules via the Python automation package.
          </p>
        )}

        {!isLoading && !isError && jobs.length > 0 && visibleJobs.length === 0 && (
          <p className="text-xs text-text-muted text-center py-8">
            Only system jobs are registered. Select Show system jobs to view them.
          </p>
        )}

        {!isLoading && visibleJobs.length > 0 && (
          <StaggeredList className="space-y-2">
            {visibleJobs.map((job) => {
              const isWorking = pendingJob === job.name;
              const isPaused  = job.status.toLowerCase() === "paused";
              const displayStatus = exploreScheduleDisplayStatus(job.status, mode);
              return (
                <div
                  key={job.name}
                  className="bg-surface-base border border-border-default rounded-lg px-4 py-3 flex items-center gap-3"
                >
                  <StatusDot status={displayStatus} />
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-0.5">
                      <p className="text-xs font-semibold text-text-primary truncate" title={job.name}>{jobLabel(job.name)}</p>
                      <StatusBadge status={displayStatus} />
                    </div>
                    <div className="flex items-center gap-3 text-xs text-text-muted">
                      <span className="font-mono">{job.trigger_type}</span>
                      <span>Last: {formatLastRun(job.last_run)}</span>
                      <span>
                        Runs: <span className="text-text-primary font-mono">{job.run_count}</span>
                      </span>
                      {job.error_count > 0 && (
                        <span className="text-loss font-mono">Errors: {job.error_count}</span>
                      )}
                    </div>
                    {job.description && (
                      <p className="text-xs text-text-muted mt-0.5 leading-tight">{job.description}</p>
                    )}
                  </div>
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => toggleJob(job)}
                    disabled={isWorking || pauseGated}
                    title={pauseGated ? SAMPLE_SCHEDULE_PAUSE_UNAVAILABLE : undefined}
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
