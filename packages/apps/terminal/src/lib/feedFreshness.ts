/**
 * FT-CORE-002 — feed-freshness honesty.
 *
 * Execution mode (Explore / Practice / Live) is independent of quote
 * provenance. Explore is always Sample. Practice and Live may show Live,
 * Delayed, Stale, or Unknown. Quotes are never silently stale.
 */

import type { AppMode } from "@/stores/modeStore";

export type FeedFreshnessState = "live" | "delayed" | "sample" | "stale" | "unknown";

export const FEED_FRESHNESS_LABEL: Record<FeedFreshnessState, string> = {
  live: "Live",
  delayed: "Delayed",
  sample: "Sample",
  stale: "Stale",
  unknown: "Unknown",
};

/**
 * Quotes older than two REST fallback poll cycles are stale.
 * Keep aligned with ``STALE_AFTER_MS`` in ``useTickerFallback``.
 */
export const FEED_STALE_AFTER_MS = 10_000;

export interface FeedFreshnessInput {
  mode: AppMode;
  wsConnected: boolean;
  fallbackActive: boolean;
  fallbackStale: boolean;
  lastTickAt: number | null;
  now: number;
}

export interface FeedFreshness {
  state: FeedFreshnessState;
  label: string;
  ageMs: number | null;
  ageLabel: string | null;
  chipText: string;
  muted: boolean;
}

function ageMsOf(lastTickAt: number | null, now: number): number | null {
  if (lastTickAt === null || lastTickAt <= 0) return null;
  return Math.max(0, now - lastTickAt);
}

/** Compact age for Stale/Unknown chips (`12s`, `3m`, `2h`). */
export function formatFeedAge(ageMs: number | null): string | null {
  if (ageMs === null || ageMs < 0 || !Number.isFinite(ageMs)) return null;
  const seconds = Math.floor(ageMs / 1000);
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m`;
  return `${Math.floor(minutes / 60)}h`;
}

function withAge(label: string, ageLabel: string | null): string {
  return ageLabel ? `${label} · ${ageLabel}` : label;
}

/**
 * Resolve the source chip for TopBar, ticker, and Market Clock.
 *
 * Explore is Sample even if a leftover WebSocket is connected (Mode honesty).
 * Live execution mode does not imply a Live feed.
 */
export function resolveFeedFreshness(input: FeedFreshnessInput): FeedFreshness {
  const ageMs = ageMsOf(input.lastTickAt, input.now);
  const ageLabel = formatFeedAge(ageMs);

  if (input.mode === "explore") {
    return {
      state: "sample",
      label: FEED_FRESHNESS_LABEL.sample,
      ageMs,
      ageLabel,
      chipText: FEED_FRESHNESS_LABEL.sample,
      muted: false,
    };
  }

  const pastWindow = ageMs !== null && ageMs > FEED_STALE_AFTER_MS;
  if (input.fallbackStale || pastWindow) {
    return {
      state: "stale",
      label: FEED_FRESHNESS_LABEL.stale,
      ageMs,
      ageLabel,
      chipText: withAge(FEED_FRESHNESS_LABEL.stale, ageLabel),
      muted: true,
    };
  }

  if (input.wsConnected && ageMs !== null) {
    return {
      state: "live",
      label: FEED_FRESHNESS_LABEL.live,
      ageMs,
      ageLabel,
      chipText: FEED_FRESHNESS_LABEL.live,
      muted: false,
    };
  }

  if (input.fallbackActive && ageMs !== null) {
    return {
      state: "delayed",
      label: FEED_FRESHNESS_LABEL.delayed,
      ageMs,
      ageLabel,
      chipText: FEED_FRESHNESS_LABEL.delayed,
      muted: false,
    };
  }

  return {
    state: "unknown",
    label: FEED_FRESHNESS_LABEL.unknown,
    ageMs,
    ageLabel,
    chipText: withAge(FEED_FRESHNESS_LABEL.unknown, ageLabel),
    muted: true,
  };
}
