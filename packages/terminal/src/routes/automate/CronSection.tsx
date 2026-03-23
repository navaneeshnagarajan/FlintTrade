/**
 * CronSection — Schedules tab.
 * Lists all registered cron jobs with pause/resume controls.
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
import { StatusDot, StatusBadge } from "./shared";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

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

  return (
    <div className="space-y-4">
      <GlassCard className="p-6">
        <div className="flex items-center justify-between mb-4">
          <div>
            <h3 className="font-heading font-semibold text-lg text-text-primary">Cron Scheduler</h3>
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
              const isPaused  = job.status.toLowerCase() === "paused";
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
