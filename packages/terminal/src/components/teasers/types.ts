/**
 * types.ts
 *
 * Shared types and constants for the teaser component library.
 * Teasers wrap upcoming / preview features with informative overlays
 * so users understand what's coming and can subscribe for notifications.
 */

// ---------------------------------------------------------------------------
// Feature status
// ---------------------------------------------------------------------------

export type FeatureStatus = "preview" | "in_dev" | "testing" | "live";

// ---------------------------------------------------------------------------
// Teaser configuration
// ---------------------------------------------------------------------------

export interface TeaserConfig {
  featureName: string;
  status: FeatureStatus;
  /** Version target, e.g. "v0.3.0" */
  version?: string;
  notifyChannel?: "telegram" | "email";
}

// ---------------------------------------------------------------------------
// Display constants
// ---------------------------------------------------------------------------

export const STATUS_LABELS: Record<FeatureStatus, string> = {
  preview: "Preview",
  in_dev: "In Development",
  testing: "Testing",
  live: "Live",
};

export const STATUS_COLORS: Record<FeatureStatus, string> = {
  preview: "text-blue-400",
  in_dev: "text-amber-400",
  testing: "text-emerald-400",
  live: "text-profit",
};

// ---------------------------------------------------------------------------
// Roadmap stages (ordered)
// ---------------------------------------------------------------------------

export const ROADMAP_STAGES: FeatureStatus[] = [
  "preview",
  "in_dev",
  "testing",
  "live",
];

export const ROADMAP_STAGE_LABELS: Record<FeatureStatus, string> = {
  preview: "Designed",
  in_dev: "In Dev",
  testing: "Testing",
  live: "Live",
};

// ---------------------------------------------------------------------------
// Notify preferences (stored in localStorage)
// ---------------------------------------------------------------------------

export interface NotifyPref {
  featureName: string;
  channel: "telegram" | "email";
  timestamp: number;
}

export const NOTIFY_PREFS_KEY = "ft-notify-prefs";
