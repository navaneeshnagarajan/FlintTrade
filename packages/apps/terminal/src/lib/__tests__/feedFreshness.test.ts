import { describe, expect, it } from "vitest";
import {
  FEED_STALE_AFTER_MS,
  formatFeedAge,
  resolveFeedFreshness,
} from "../feedFreshness";

const NOW = 1_700_000_000_000;

function resolve(
  overrides: Partial<Parameters<typeof resolveFeedFreshness>[0]> = {},
) {
  return resolveFeedFreshness({
    mode: "live",
    wsConnected: false,
    fallbackActive: false,
    fallbackStale: false,
    lastTickAt: null,
    now: NOW,
    ...overrides,
  });
}

describe("FT-CORE-002 feed freshness", () => {
  it("Explore is always Sample, even when a leftover live feed is connected", () => {
    const freshness = resolve({
      mode: "explore",
      wsConnected: true,
      lastTickAt: NOW - 200,
    });
    expect(freshness.state).toBe("sample");
    expect(freshness.label).toBe("Sample");
    expect(freshness.chipText).toBe("Sample");
    expect(freshness.muted).toBe(false);
    expect(freshness.chipText).not.toMatch(/Live|Practice/i);
  });

  it("Practice with a fresh WebSocket tick is Live, not Sample", () => {
    const freshness = resolve({
      mode: "practice",
      wsConnected: true,
      lastTickAt: NOW - 400,
    });
    expect(freshness.state).toBe("live");
    expect(freshness.label).toBe("Live");
    expect(freshness.chipText).toBe("Live");
    expect(freshness.muted).toBe(false);
  });

  it("REST fallback snapshots are Delayed, not Live", () => {
    const freshness = resolve({
      mode: "live",
      wsConnected: false,
      fallbackActive: true,
      lastTickAt: NOW - 1_000,
    });
    expect(freshness.state).toBe("delayed");
    expect(freshness.label).toBe("Delayed");
    expect(freshness.chipText).toBe("Delayed");
    expect(freshness.muted).toBe(false);
  });

  it("stale quotes show muted Stale plus age", () => {
    const freshness = resolve({
      mode: "live",
      wsConnected: true,
      lastTickAt: NOW - FEED_STALE_AFTER_MS - 2_000,
    });
    expect(freshness.state).toBe("stale");
    expect(freshness.label).toBe("Stale");
    expect(freshness.muted).toBe(true);
    expect(freshness.ageLabel).toBe("12s");
    expect(freshness.chipText).toBe("Stale · 12s");
  });

  it("fallback-reported staleness is muted Stale even if the clock is still inside the window", () => {
    const freshness = resolve({
      mode: "live",
      fallbackActive: true,
      fallbackStale: true,
      lastTickAt: NOW - 1_000,
    });
    expect(freshness.state).toBe("stale");
    expect(freshness.muted).toBe(true);
    expect(freshness.chipText).toMatch(/^Stale/);
  });

  it("unknown source with a known age is muted Unknown plus age", () => {
    const freshness = resolve({
      mode: "live",
      lastTickAt: NOW - 5_000,
    });
    expect(freshness.state).toBe("unknown");
    expect(freshness.label).toBe("Unknown");
    expect(freshness.muted).toBe(true);
    expect(freshness.ageLabel).toBe("5s");
    expect(freshness.chipText).toBe("Unknown · 5s");
  });

  it("unknown source with no timestamp is muted Unknown without inventing an age", () => {
    const freshness = resolve({ mode: "practice" });
    expect(freshness.state).toBe("unknown");
    expect(freshness.chipText).toBe("Unknown");
    expect(freshness.ageLabel).toBeNull();
    expect(freshness.muted).toBe(true);
  });

  it("Live mode does not imply a Live feed (Mode honesty)", () => {
    const freshness = resolve({ mode: "live", fallbackActive: true, lastTickAt: NOW - 800 });
    expect(freshness.state).toBe("delayed");
    expect(freshness.chipText).toBe("Delayed");
  });

  it("formats age in seconds, minutes, and hours", () => {
    expect(formatFeedAge(null)).toBeNull();
    expect(formatFeedAge(-1)).toBeNull();
    expect(formatFeedAge(0)).toBe("0s");
    expect(formatFeedAge(12_000)).toBe("12s");
    expect(formatFeedAge(60_000)).toBe("1m");
    expect(formatFeedAge(3_600_000)).toBe("1h");
  });
});
