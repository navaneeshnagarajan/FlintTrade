/**
 * RoadmapBadge.tsx
 *
 * A 4-stage animated progress indicator:
 *   Designed → In Dev → Testing → Live
 *
 * Visuals:
 *   - 4 dots connected by lines
 *   - Completed stages: solid accent color, filled
 *   - Active stage: larger, pulse-glow animation, accent color
 *   - Future stages: muted border only
 *
 * Framer Motion `layoutId` is used on the active indicator so it
 * animates smoothly if the status changes at runtime.
 *
 * Respects `prefers-reduced-motion` — pulse and layout animations are
 * disabled when the OS setting is active.
 */

import { motion } from "framer-motion";
import { cn } from "@/lib/utils";
import { motionConfig, EASE_ENTER, DURATION } from "@/lib/motion";
import {
  ROADMAP_STAGES,
  ROADMAP_STAGE_LABELS,
  type FeatureStatus,
} from "./types";

// ---------------------------------------------------------------------------
// Stage index helpers
// ---------------------------------------------------------------------------

function stageIndex(status: FeatureStatus): number {
  return ROADMAP_STAGES.indexOf(status);
}

// ---------------------------------------------------------------------------
// Sub-component — single stage dot
// ---------------------------------------------------------------------------

interface StageDotProps {
  stage: FeatureStatus;
  activeIndex: number;
  index: number;
  reduceMotion: boolean;
}

function StageDot({ stage, activeIndex, index, reduceMotion }: StageDotProps) {
  const isActive = index === activeIndex;
  const isCompleted = index < activeIndex;
  const isFuture = index > activeIndex;
  const label = ROADMAP_STAGE_LABELS[stage];

  return (
    <div className="flex flex-col items-center gap-1 relative">
      {/* Dot container — fixed size so the inner glow ring doesn't shift layout */}
      <div className="relative flex items-center justify-center w-5 h-5">
        {/* Pulse glow ring — active state only */}
        {isActive && !reduceMotion && (
          <motion.div
            className="absolute inset-0 rounded-full"
            style={{ background: "rgba(59,130,246,0.25)" }}
            animate={{ scale: [1, 1.8, 1], opacity: [0.6, 0, 0.6] }}
            transition={{
              duration: 2,
              repeat: Infinity,
              ease: "easeInOut",
            }}
            aria-hidden="true"
          />
        )}

        {/* Active indicator — uses layoutId for smooth transition on status change */}
        {isActive && (
          <motion.div
            layoutId="roadmap-active"
            className="absolute inset-0 rounded-full bg-blue-400"
            transition={
              reduceMotion
                ? { duration: 0 }
                : { duration: DURATION.normal, ease: EASE_ENTER }
            }
            aria-hidden="true"
          />
        )}

        {/* Dot fill */}
        <div
          className={cn(
            "relative z-10 rounded-full transition-[width,height] duration-200",
            isActive && "w-3 h-3 bg-blue-400",
            isCompleted && "w-2.5 h-2.5 bg-blue-400",
            isFuture && "w-2 h-2 border border-border-default bg-transparent",
          )}
          role="img"
          aria-label={`${label}: ${isActive ? "current" : isCompleted ? "completed" : "upcoming"}`}
        />
      </div>

      {/* Stage label */}
      <span
        className={cn(
          "text-[10px] font-medium whitespace-nowrap transition-colors duration-200",
          isActive && "text-blue-400",
          isCompleted && "text-text-secondary",
          isFuture && "text-text-muted",
        )}
      >
        {label}
      </span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Sub-component — connector line between dots
// ---------------------------------------------------------------------------

interface ConnectorProps {
  leftIndex: number;
  activeIndex: number;
}

function Connector({ leftIndex, activeIndex }: ConnectorProps) {
  const isFilled = leftIndex < activeIndex;

  return (
    <div
      className="relative flex-1 mx-1 h-px mt-2.5"
      aria-hidden="true"
    >
      {/* Base line */}
      <div className="absolute inset-0 bg-border-default" />
      {/* Filled portion */}
      {isFilled && (
        <motion.div
          className="absolute inset-0 bg-blue-400"
          initial={{ scaleX: 0, originX: 0 }}
          animate={{ scaleX: 1 }}
          transition={{ duration: DURATION.slow, ease: EASE_ENTER }}
        />
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

interface RoadmapBadgeProps {
  status: FeatureStatus;
  className?: string;
}

export function RoadmapBadge({ status, className }: RoadmapBadgeProps) {
  const activeIndex = stageIndex(status);
  const reduceMotion = motionConfig.prefersReducedMotion();

  return (
    <div
      role="group"
      aria-label={`Feature roadmap — current stage: ${ROADMAP_STAGE_LABELS[status]}`}
      className={cn("flex items-start w-full px-1", className)}
    >
      {ROADMAP_STAGES.map((stage, i) => (
        <div key={stage} className="flex items-start flex-1">
          <StageDot
            stage={stage}
            activeIndex={activeIndex}
            index={i}
            reduceMotion={reduceMotion}
          />
          {/* Connector after every stage except the last */}
          {i < ROADMAP_STAGES.length - 1 && (
            <Connector leftIndex={i} activeIndex={activeIndex} />
          )}
        </div>
      ))}
    </div>
  );
}

export default RoadmapBadge;
