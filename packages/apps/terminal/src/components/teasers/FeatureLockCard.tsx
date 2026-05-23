/**
 * FeatureLockCard.tsx
 *
 * A fully locked feature card — used when a feature has no preview available.
 * Shows: icon, feature name, description, RoadmapBadge, NotifyMe CTA.
 *
 * Visual design:
 *   - HoverCard from aceternity: cursor-following radial glow on border
 *   - Muted/dimmed appearance (opacity 0.85 default)
 *   - Slight scale-up on hover (1.0 → 1.02)
 *   - Lock icon overlay in top-right corner
 *
 * Accessibility:
 *   - aria-label on the card summarises feature name + status
 *   - Lock badge has aria-hidden (decorative)
 *   - All interactive children remain keyboard navigable
 */

import { type ReactNode } from "react";
import { motion } from "framer-motion";
import { Lock } from "lucide-react";
import { HoverCard } from "@/components/aceternity/card-hover-effect";
import { cn } from "@/lib/utils";
import { motionConfig, EASE_ENTER, DURATION } from "@/lib/motion";
import { RoadmapBadge } from "./RoadmapBadge";
import { NotifyMe } from "./NotifyMe";
import { STATUS_LABELS, STATUS_COLORS, type TeaserConfig } from "./types";

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

interface FeatureLockCardProps {
  config: TeaserConfig;
  /** Icon element to display (e.g. <BarChart2 size={20} />) */
  icon?: ReactNode;
  /** Short description of the feature */
  description?: string;
  className?: string;
}

export function FeatureLockCard({
  config,
  icon,
  description,
  className,
}: FeatureLockCardProps) {
  const { featureName, status, version } = config;
  const statusLabel = STATUS_LABELS[status];
  const statusColor = STATUS_COLORS[status];

  const reduceMotion = motionConfig.prefersReducedMotion();

  return (
    <motion.div
      className={cn("w-full", className)}
      initial={{ opacity: 0, y: 8 }}
      animate={{
        opacity: 1,
        y: 0,
        transition: { duration: DURATION.slow, ease: EASE_ENTER },
      }}
      whileHover={
        reduceMotion
          ? undefined
          : { scale: 1.02, transition: { duration: DURATION.fast, ease: EASE_ENTER } }
      }
      aria-label={`${featureName} — ${statusLabel}${version ? `, target ${version}` : ""}`}
    >
      <HoverCard className={cn("p-4", className)}>
        {/* Lock badge — decorative */}
        <div
          className="absolute top-3 right-3 flex items-center gap-1 rounded px-1.5 py-0.5 bg-surface-card/80 border border-border-default"
          aria-hidden="true"
        >
          <Lock size={10} className="text-text-muted" />
          <span className="text-[10px] text-text-muted font-medium">
            Locked
          </span>
        </div>

        {/* Header — icon + feature name */}
        <div className="flex items-start gap-3 mb-3 pr-12">
          {icon && (
            <div className="shrink-0 p-2 rounded-lg bg-surface-card border border-border-default text-text-secondary">
              {icon}
            </div>
          )}
          <div className="min-w-0">
            <h3 className="text-sm font-semibold text-text-primary truncate">
              {featureName}
            </h3>
            <div className="flex items-center gap-1.5 mt-0.5">
              <span className={cn("text-[10px] font-medium uppercase tracking-wider", statusColor)}>
                {statusLabel}
              </span>
              {version && (
                <span className="text-[10px] text-text-muted font-mono">
                  · {version}
                </span>
              )}
            </div>
          </div>
        </div>

        {/* Description */}
        {description && (
          <p className="text-xs text-text-secondary leading-relaxed mb-4">
            {description}
          </p>
        )}

        {/* Roadmap progress */}
        <div className="mb-4">
          <RoadmapBadge status={status} />
        </div>

        {/* Notify CTA */}
        <NotifyMe config={config} />
      </HoverCard>
    </motion.div>
  );
}

export default FeatureLockCard;
