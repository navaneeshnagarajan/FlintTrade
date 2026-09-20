/**
 * Explore Schedules Pause gate (FT-AUTO-004).
 *
 * Banner owns Sample disclosure. Seeded / leaked Explore jobs must not look
 * production-Active, and Pause stays unavailable.
 */

import { describe, expect, it } from "vitest";
import {
  SAMPLE_SCHEDULE_PAUSE_UNAVAILABLE,
  SEEDED_EXPLORE_SCHEDULE_JOBS,
  exploreScheduleDisplayStatus,
  isExploreScheduleControlGated,
  resolveExploreScheduleJobs,
} from "../exploreScheduleGate";

describe("exploreScheduleGate", () => {
  it("uses the locked Pause helper title", () => {
    expect(SAMPLE_SCHEDULE_PAUSE_UNAVAILABLE).toBe(
      "Sample schedule — control unavailable in Explore",
    );
  });

  it("gates Pause only in Explore", () => {
    expect(isExploreScheduleControlGated("explore")).toBe(true);
    expect(isExploreScheduleControlGated("practice")).toBe(false);
    expect(isExploreScheduleControlGated("live")).toBe(false);
  });

  it("remints Active Explore jobs to Sample and muted paused jobs to Demo", () => {
    expect(exploreScheduleDisplayStatus("ACTIVE", "explore")).toBe("Sample");
    expect(exploreScheduleDisplayStatus("active", "explore")).toBe("Sample");
    expect(exploreScheduleDisplayStatus("PAUSED", "explore")).toBe("Demo");
    expect(exploreScheduleDisplayStatus("paused", "explore")).toBe("Demo");
  });

  it("leaves Practice and Live statuses untouched", () => {
    expect(exploreScheduleDisplayStatus("ACTIVE", "practice")).toBe("ACTIVE");
    expect(exploreScheduleDisplayStatus("PAUSED", "live")).toBe("PAUSED");
    expect(exploreScheduleDisplayStatus("error", "live")).toBe("error");
  });

  it("keeps leaked API rows and seeds only when Explore has none", () => {
    const leaked = [{
      name: "health_check_job",
      description: "Verify OpenAlgo session",
      trigger_type: "cron",
      status: "ACTIVE",
      last_run: null,
      run_count: 0,
      error_count: 0,
    }];
    expect(resolveExploreScheduleJobs(leaked, false)).toEqual(leaked);
    expect(resolveExploreScheduleJobs([], true)).toEqual([]);
    expect(resolveExploreScheduleJobs([], false)).toEqual(SEEDED_EXPLORE_SCHEDULE_JOBS);
  });
});
