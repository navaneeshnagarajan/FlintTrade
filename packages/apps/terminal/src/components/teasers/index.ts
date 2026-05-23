/**
 * Teaser component library — barrel export
 *
 * Usage:
 *   import { FeatureTeaser, FeatureLockCard, PreviewBanner } from "@/components/teasers";
 */

export { FeatureTeaser } from "./FeatureTeaser";
export { FeatureLockCard } from "./FeatureLockCard";
export { PreviewBanner } from "./PreviewBanner";
export { RoadmapBadge } from "./RoadmapBadge";
export { NotifyMe } from "./NotifyMe";

export type {
  FeatureStatus,
  TeaserConfig,
  NotifyPref,
} from "./types";

export {
  STATUS_LABELS,
  STATUS_COLORS,
  ROADMAP_STAGES,
  ROADMAP_STAGE_LABELS,
  NOTIFY_PREFS_KEY,
} from "./types";
