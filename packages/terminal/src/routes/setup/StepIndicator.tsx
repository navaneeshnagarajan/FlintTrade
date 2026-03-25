/**
 * StepIndicator — clickable progress dots for the setup wizard.
 */

import { motion } from "framer-motion";
import { Check } from "lucide-react";
import { motionConfig } from "@/lib/motion";

export interface StepIndicatorProps {
  total: number;
  current: number;
  /** Optional: called when user clicks a completed step dot */
  onStepClick?: (index: number) => void;
}

export function StepIndicator({ total, current, onStepClick }: StepIndicatorProps) {
  const reduced = motionConfig.prefersReducedMotion();

  return (
    <div
      className="flex items-center gap-3 justify-center"
      aria-label={`Setup progress: step ${current + 1} of ${total}`}
    >
      {Array.from({ length: total }, (_, i) => {
        const isCompleted = i < current;
        const isActive = i === current;
        const isFuture = i > current;
        const isClickable = i <= current && onStepClick !== undefined;

        return (
          <button
            key={i}
            type="button"
            aria-label={`Step ${i + 1}${isCompleted ? " (completed)" : isActive ? " (current)" : " (upcoming)"}`}
            aria-disabled={isFuture}
            disabled={isFuture}
            onClick={isClickable ? () => onStepClick(i) : undefined}
            className={[
              "relative flex items-center justify-center rounded-full transition-all duration-300 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/50",
              isActive ? "size-5 bg-primary cursor-default" : isCompleted ? "size-4 bg-profit cursor-pointer hover:ring-2 hover:ring-profit/40" : "size-3 bg-border-default cursor-not-allowed opacity-50",
            ].join(" ")}
          >
            {isActive && !reduced && (
              <motion.span
                layoutId="step-active-ring"
                className="absolute inset-0 rounded-full ring-2 ring-primary/40"
                transition={motionConfig.transitions.tab}
              />
            )}
            {isCompleted && (
              <Check className="size-2.5 text-surface-base" strokeWidth={3} />
            )}
          </button>
        );
      })}
    </div>
  );
}
