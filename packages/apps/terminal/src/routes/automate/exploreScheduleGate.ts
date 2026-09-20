/**
 * Explore Schedules Pause gate (FT-AUTO-004).
 *
 * The global Explore sample banner owns disclosure. Seeded (or leaked)
 * Explore jobs must not look production-Active, and Pause stays
 * unavailable. Practice / Live keep Pause / Resume.
 */

import type { CronJob } from "@/services/ftApi";
import type { AppMode } from "@/stores/modeStore";

export const SAMPLE_SCHEDULE_PAUSE_UNAVAILABLE =
  "Sample schedule — control unavailable in Explore";

export const SEEDED_EXPLORE_SCHEDULE_JOBS: CronJob[] = [
  {
    name: "pre-market-screener",
    description: "Run pre-market screener at 9:00 AM IST every weekday",
    trigger_type: "cron",
    status: "Sample",
    last_run: null,
    run_count: 0,
    error_count: 0,
  },
  {
    name: "eod-position-snapshot",
    description: "Snapshot positions to a CSV at 3:30 PM IST",
    trigger_type: "cron",
    status: "Sample",
    last_run: null,
    run_count: 0,
    error_count: 0,
  },
];

/** True when Schedules Pause / Resume must stay unavailable. */
export function isExploreScheduleControlGated(mode: AppMode | string): boolean {
  return mode === "explore";
}

/**
 * Remint an Explore job status so it cannot read as a live Active badge.
 *
 * Active → Sample; paused → Demo; other values stay as-is (muted fallback).
 * Practice / Live statuses pass through unchanged.
 */
export function exploreScheduleDisplayStatus(
  status: string,
  mode: AppMode | string,
): string {
  if (mode !== "explore") return status;
  const lower = status.toLowerCase();
  if (lower === "active") return "Sample";
  if (lower === "paused") return "Demo";
  return status;
}

/** Jobs shown on Explore Schedules: reminted API rows, or the seeded sample set. */
export function resolveExploreScheduleJobs(
  apiJobs: CronJob[],
  isLoading: boolean,
): CronJob[] {
  if (apiJobs.length > 0) return apiJobs;
  if (isLoading) return [];
  return SEEDED_EXPLORE_SCHEDULE_JOBS;
}
