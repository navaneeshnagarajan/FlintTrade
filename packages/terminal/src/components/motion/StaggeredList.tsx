/**
 * StaggeredList.tsx
 *
 * Wraps each direct child in a staggered fade-in animation using
 * Framer Motion. Each child slides up and fades in with an incremental
 * delay based on its index.
 *
 * When the user has requested reduced motion via their OS/browser setting
 * (prefers-reduced-motion: reduce), children are rendered immediately
 * without any animation.
 *
 * Usage:
 *   <StaggeredList>
 *     <Card>…</Card>
 *     <Card>…</Card>
 *     <Card>…</Card>
 *   </StaggeredList>
 *
 *   <StaggeredList staggerDelay={60} className="grid grid-cols-3 gap-4">
 *     …
 *   </StaggeredList>
 */

import * as React from "react";
import { motion, AnimatePresence } from "framer-motion";
import { motionConfig } from "@/lib/motion";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface StaggeredListProps {
  children: React.ReactNode;
  className?: string;
  /**
   * Milliseconds of additional delay between each child item.
   * Default: 40 ms (converted to 0.04 s when passed to Framer Motion).
   */
  staggerDelay?: number;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function StaggeredList({
  children,
  className,
  staggerDelay = 40,
}: StaggeredListProps) {
  const reducedMotion = motionConfig.prefersReducedMotion();

  // Convert ms → seconds for Framer Motion
  const stepSeconds = staggerDelay / 1000;

  // When reduced motion is preferred, render children directly — no wrappers,
  // no animation overhead.
  if (reducedMotion) {
    return <div className={className}>{children}</div>;
  }

  return (
    <AnimatePresence initial={false}>
      <div className={className}>
        {React.Children.map(children, (child, index) => {
          // Skip null / undefined children so the index stays predictable
          if (child === null || child === undefined) return null;

          const transition = motionConfig.stagger(
            index,
            { duration: motionConfig.duration.slow, ease: motionConfig.ease.enter },
            stepSeconds,
          );

          return (
            <motion.div
              key={index}
              variants={motionConfig.variants.fadeIn}
              initial="initial"
              animate="animate"
              exit="exit"
              transition={transition}
            >
              {child}
            </motion.div>
          );
        })}
      </div>
    </AnimatePresence>
  );
}

export default StaggeredList;
