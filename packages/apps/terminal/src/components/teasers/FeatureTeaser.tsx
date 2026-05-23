/**
 * FeatureTeaser.tsx
 *
 * Main wrapper component — wraps real widget content with a teaser overlay.
 *
 * Behaviour:
 *   - Renders `children` (the actual widget with sample data) at slight opacity
 *   - Overlays PreviewBanner at the top of the container
 *   - Shows a floating panel (RoadmapBadge + NotifyMe) at bottom-right
 *   - When `status === "live"`, renders children normally — no overlay
 *
 * Layout:
 *   - Relative-positioned container
 *   - Children rendered at 0.6 opacity with pointer-events disabled
 *   - PreviewBanner pinned top, full-width, z-10
 *   - Floating panel pinned bottom-right, z-10
 *   - Semi-transparent dark veil between content and overlays
 *
 * Animation:
 *   - Overlay veil fades in (opacity 0 → 1)
 *   - Floating panel slides up from below (y 8 → 0)
 *   - Children are always visible (dimmed, not hidden)
 *   - Respects prefers-reduced-motion
 *
 * Accessibility:
 *   - region aria-label describes the teaser
 *   - Children wrapped in aria-hidden when overlaid (pointer-events none + hidden)
 *   - Overlay elements are keyboard navigable
 */

import { type ReactNode } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { cn } from "@/lib/utils";
import { motionConfig, EASE_ENTER, DURATION } from "@/lib/motion";
import { PreviewBanner } from "./PreviewBanner";
import { RoadmapBadge } from "./RoadmapBadge";
import { NotifyMe } from "./NotifyMe";
import { STATUS_LABELS, type TeaserConfig } from "./types";

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

interface FeatureTeaserProps extends TeaserConfig {
  children: ReactNode;
  className?: string;
}

export function FeatureTeaser({
  children,
  className,
  // Destructure all TeaserConfig fields
  featureName,
  status,
  version,
  notifyChannel,
}: FeatureTeaserProps) {
  const config: TeaserConfig = { featureName, status, version, notifyChannel };
  const reduceMotion = motionConfig.prefersReducedMotion();

  // When live, render children normally — no teaser overhead
  if (status === "live") {
    return <>{children}</>;
  }

  const veilVariants = {
    initial: { opacity: 0 },
    animate: {
      opacity: 1,
      transition: { duration: DURATION.slow, ease: EASE_ENTER },
    },
    exit: {
      opacity: 0,
      transition: { duration: DURATION.fast },
    },
  };

  const floatingPanelVariants = {
    initial: reduceMotion ? { opacity: 0 } : { opacity: 0, y: 8 },
    animate: reduceMotion
      ? { opacity: 1, transition: { duration: DURATION.normal } }
      : {
          opacity: 1,
          y: 0,
          transition: {
            duration: DURATION.slow,
            ease: EASE_ENTER,
            delay: 0.1,
          },
        },
    exit: {
      opacity: 0,
      transition: { duration: DURATION.fast },
    },
  };

  return (
    <section
      aria-label={`${featureName} — ${STATUS_LABELS[status]} preview`}
      className={cn("relative w-full h-full min-h-0 overflow-hidden", className)}
    >
      {/* Widget content — dimmed, pointer-events disabled while teaser is active */}
      <div
        className="w-full h-full"
        aria-hidden="true"
        style={{
          opacity: 0.6,
          pointerEvents: "none",
          userSelect: "none",
        }}
      >
        {children}
      </div>

      {/* Teaser overlay layer */}
      <AnimatePresence>
        <>
          {/* Semi-transparent veil */}
          <motion.div
            key="teaser-veil"
            variants={veilVariants}
            initial="initial"
            animate="animate"
            exit="exit"
            aria-hidden="true"
            className="absolute inset-0 pointer-events-none"
            style={{
              background:
                "linear-gradient(to bottom, rgba(10,10,15,0.45) 0%, rgba(10,10,15,0.2) 50%, rgba(10,10,15,0.55) 100%)",
            }}
          />

          {/* Preview banner — top, full width */}
          <div className="absolute top-0 left-0 right-0 z-10 p-2">
            <PreviewBanner config={config} />
          </div>

          {/* Floating panel — bottom-right */}
          <motion.div
            key="teaser-floating-panel"
            variants={floatingPanelVariants}
            initial="initial"
            animate="animate"
            exit="exit"
            className={cn(
              "absolute bottom-3 right-3 z-10",
              "flex flex-col gap-2 p-3 rounded-xl",
              "bg-surface-card/90 border border-border-default",
              "backdrop-blur-sm",
              "min-w-[180px] max-w-[220px]",
            )}
            style={{
              backdropFilter: "blur(8px)",
              WebkitBackdropFilter: "blur(8px)",
            }}
          >
            <RoadmapBadge status={status} />
            <NotifyMe config={config} />
          </motion.div>
        </>
      </AnimatePresence>
    </section>
  );
}

export default FeatureTeaser;
