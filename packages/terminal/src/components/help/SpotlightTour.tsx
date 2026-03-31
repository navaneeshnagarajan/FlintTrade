/**
 * SpotlightTour.tsx
 *
 * A data-attribute-based guided tour that highlights DOM elements with a
 * spotlight overlay and shows step cards next to each target.
 *
 * Replaces the old InteractiveTour (which used hardcoded absolute positions
 * for dots) with a system that finds targets via `data-tour-target` attributes,
 * making tours work regardless of layout changes.
 *
 * Behaviour:
 *   - Only shows when `helpPrefs.spotlightTours` is true
 *   - Only triggers if `ft-tour-completed-{tourId}` is NOT in localStorage
 *   - Finds target element via `document.querySelector('[data-tour-target="..."]')`
 *   - Highlights target with a spotlight effect (dark overlay with SVG cutout)
 *   - Shows step card positioned relative to the target element
 *   - Next / Back / Skip buttons for navigation
 *   - On complete: stores `ft-tour-completed-{tourId}` in localStorage
 *   - Framer Motion: smooth transition between steps
 *   - WCAG: focus trapped in step card, Escape skips tour
 *
 * Usage:
 *   <SpotlightTour
 *     tourId="trade-beginner"
 *     steps={TOUR_DEFINITIONS["trade-beginner"]}
 *     onComplete={() => console.log("Tour done")}
 *   />
 *
 * Target elements must have:
 *   <div data-tour-target="watchlist">...</div>
 */

import {
  useState,
  useEffect,
  useCallback,
  useRef,
  type KeyboardEvent as ReactKeyboardEvent,
} from "react";
import { motion, AnimatePresence } from "framer-motion";
import { X, ChevronRight, ChevronLeft } from "lucide-react";
import { useHelpPrefs } from "@/hooks/useHelpPrefs";
import { DURATION, EASE_ENTER, EASE_EXIT, EASE_MOVE } from "@/lib/motion";
import { cn } from "@/lib/utils";
import type { TourStep } from "@/lib/tourDefinitions";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type { TourStep };

export interface SpotlightTourProps {
  /** Unique tour identifier, e.g. "trade-beginner" */
  tourId: string;
  /** Ordered list of tour steps */
  steps: TourStep[];
  /** Callback when the tour is completed or skipped */
  onComplete?: () => void;
}

// ---------------------------------------------------------------------------
// localStorage helpers
// ---------------------------------------------------------------------------

function completionKey(tourId: string): string {
  return `ft-tour-completed-${tourId}`;
}

function isTourCompleted(tourId: string): boolean {
  try {
    return localStorage.getItem(completionKey(tourId)) === "true";
  } catch {
    return false;
  }
}

function markTourCompleted(tourId: string): void {
  try {
    localStorage.setItem(completionKey(tourId), "true");
  } catch {
    // Silently ignore
  }
}

// ---------------------------------------------------------------------------
// Geometry helpers
// ---------------------------------------------------------------------------

interface TargetRect {
  top: number;
  left: number;
  width: number;
  height: number;
  right: number;
  bottom: number;
}

const SPOTLIGHT_PADDING = 8;

function getTargetRect(target: string): TargetRect | null {
  const el = document.querySelector(`[data-tour-target="${target}"]`);
  if (!el) return null;
  const rect = el.getBoundingClientRect();
  return {
    top: rect.top - SPOTLIGHT_PADDING,
    left: rect.left - SPOTLIGHT_PADDING,
    width: rect.width + SPOTLIGHT_PADDING * 2,
    height: rect.height + SPOTLIGHT_PADDING * 2,
    right: rect.right + SPOTLIGHT_PADDING,
    bottom: rect.bottom + SPOTLIGHT_PADDING,
  };
}

// ---------------------------------------------------------------------------
// Step card position calculator
// ---------------------------------------------------------------------------

const CARD_OFFSET = 12;

interface CardPosition {
  top?: number;
  left?: number;
  right?: number;
  bottom?: number;
}

function computeCardPosition(
  rect: TargetRect,
  position: TourStep["position"] = "bottom",
): CardPosition {
  switch (position) {
    case "top":
      return {
        bottom: window.innerHeight - rect.top + CARD_OFFSET,
        left: rect.left,
      };
    case "left":
      return {
        top: rect.top,
        right: window.innerWidth - rect.left + CARD_OFFSET,
      };
    case "right":
      return {
        top: rect.top,
        left: rect.right + CARD_OFFSET,
      };
    case "bottom":
    default:
      return {
        top: rect.bottom + CARD_OFFSET,
        left: rect.left,
      };
  }
}

// ---------------------------------------------------------------------------
// Animation variants
// ---------------------------------------------------------------------------

const overlayVariants = {
  initial: { opacity: 0 },
  animate: {
    opacity: 1,
    transition: { duration: DURATION.normal, ease: EASE_ENTER },
  },
  exit: {
    opacity: 0,
    transition: { duration: DURATION.fast, ease: EASE_EXIT },
  },
};

const cardVariants = {
  initial: { opacity: 0, y: 8, scale: 0.96 },
  animate: {
    opacity: 1,
    y: 0,
    scale: 1,
    transition: { duration: DURATION.slow, ease: EASE_ENTER },
  },
  exit: {
    opacity: 0,
    y: -4,
    scale: 0.98,
    transition: { duration: DURATION.fast, ease: EASE_EXIT },
  },
};

const spotlightTransition = {
  duration: DURATION.slow,
  ease: EASE_MOVE,
};

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function SpotlightTour({
  tourId,
  steps,
  onComplete,
}: SpotlightTourProps) {
  const helpPrefs = useHelpPrefs();
  const [currentStep, setCurrentStep] = useState(0);
  const [targetRect, setTargetRect] = useState<TargetRect | null>(null);
  const [visible, setVisible] = useState(() => {
    return !isTourCompleted(tourId);
  });
  const cardRef = useRef<HTMLDivElement>(null);

  // Resolve target rect when step changes
  useEffect(() => {
    if (!visible || steps.length === 0) return;

    const step = steps[currentStep];
    if (!step) return;

    // Slight delay to allow DOM to settle (e.g. after route transition)
    const timer = setTimeout(() => {
      setTargetRect(getTargetRect(step.target));
    }, 50);

    return () => clearTimeout(timer);
  }, [visible, currentStep, steps]);

  // Recalculate on window resize
  useEffect(() => {
    if (!visible) return;

    const handleResize = () => {
      const step = steps[currentStep];
      if (step) {
        setTargetRect(getTargetRect(step.target));
      }
    };

    window.addEventListener("resize", handleResize);
    return () => window.removeEventListener("resize", handleResize);
  }, [visible, currentStep, steps]);

  // Focus trap: keep focus in the step card
  useEffect(() => {
    if (!visible || !cardRef.current) return;
    cardRef.current.focus();
  }, [visible, currentStep]);

  const finish = useCallback(() => {
    markTourCompleted(tourId);
    setVisible(false);
    onComplete?.();
  }, [tourId, onComplete]);

  const handleSkip = useCallback(() => {
    finish();
  }, [finish]);

  const handleNext = useCallback(() => {
    if (currentStep < steps.length - 1) {
      setCurrentStep((s) => s + 1);
    } else {
      finish();
    }
  }, [currentStep, steps.length, finish]);

  const handleBack = useCallback(() => {
    if (currentStep > 0) {
      setCurrentStep((s) => s - 1);
    }
  }, [currentStep]);

  const handleKeyDown = useCallback(
    (e: ReactKeyboardEvent<HTMLDivElement>) => {
      if (e.key === "Escape") {
        e.preventDefault();
        handleSkip();
      } else if (e.key === "ArrowRight" || e.key === "Enter") {
        e.preventDefault();
        handleNext();
      } else if (e.key === "ArrowLeft") {
        e.preventDefault();
        handleBack();
      }
    },
    [handleSkip, handleNext, handleBack],
  );

  // Do not render if hidden, prefs disabled, or no steps
  if (!visible || !helpPrefs.spotlightTours || steps.length === 0) {
    return null;
  }

  const step = steps[currentStep];
  if (!step) return null;

  const isFirst = currentStep === 0;
  const isLast = currentStep === steps.length - 1;
  const cardPosition = targetRect
    ? computeCardPosition(targetRect, step.position)
    : { top: "50%", left: "50%" };

  return (
    <AnimatePresence>
      {visible && (
        <div
          role="dialog"
          aria-label={`Guided tour: ${tourId}`}
          aria-modal="true"
          className="fixed inset-0 z-[9998]"
          data-testid="spotlight-tour"
        >
          {/* Dark overlay with spotlight cutout */}
          <motion.div
            key="spotlight-overlay"
            variants={overlayVariants}
            initial="initial"
            animate="animate"
            exit="exit"
            className="absolute inset-0"
            aria-hidden="true"
          >
            <svg
              className="absolute inset-0 w-full h-full"
              xmlns="http://www.w3.org/2000/svg"
            >
              <defs>
                <mask id={`spotlight-mask-${tourId}`}>
                  <rect width="100%" height="100%" fill="white" />
                  {targetRect && (
                    <motion.rect
                      x={targetRect.left}
                      y={targetRect.top}
                      width={targetRect.width}
                      height={targetRect.height}
                      rx={8}
                      fill="black"
                      animate={{
                        x: targetRect.left,
                        y: targetRect.top,
                        width: targetRect.width,
                        height: targetRect.height,
                      }}
                      transition={spotlightTransition}
                    />
                  )}
                </mask>
              </defs>
              <rect
                width="100%"
                height="100%"
                fill="rgba(0,0,0,0.6)"
                mask={`url(#spotlight-mask-${tourId})`}
              />
            </svg>
          </motion.div>

          {/* Step card */}
          <AnimatePresence mode="wait">
            <motion.div
              key={`step-${currentStep}`}
              ref={cardRef}
              tabIndex={-1}
              variants={cardVariants}
              initial="initial"
              animate="animate"
              exit="exit"
              onKeyDown={handleKeyDown}
              className={cn(
                "absolute z-[9999]",
                "w-[280px] rounded-xl p-4",
                "border border-border-default/50",
                "bg-surface-card/85",
                "text-text-primary shadow-xl",
                "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent",
              )}
              style={{
                ...cardPosition,
                backdropFilter: "blur(16px)",
                WebkitBackdropFilter: "blur(16px)",
              }}
            >
              {/* Header */}
              <div className="flex items-start justify-between gap-2 mb-2">
                <h3 className="font-heading font-semibold text-sm leading-snug">
                  {step.title}
                </h3>
                <button
                  type="button"
                  onClick={handleSkip}
                  aria-label="Skip tour"
                  className={cn(
                    "shrink-0 h-5 w-5 rounded",
                    "text-text-muted hover:text-text-primary",
                    "transition-colors duration-150",
                    "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                  )}
                >
                  <X className="h-3.5 w-3.5" />
                </button>
              </div>

              {/* Description */}
              <p className="text-xs text-text-secondary leading-relaxed mb-4">
                {step.description}
              </p>

              {/* Footer: progress + navigation */}
              <div className="flex items-center justify-between">
                {/* Step counter */}
                <span className="text-xxs text-text-muted tabular-nums">
                  {currentStep + 1} of {steps.length}
                </span>

                {/* Navigation buttons */}
                <div className="flex items-center gap-1.5">
                  {!isFirst && (
                    <button
                      type="button"
                      onClick={handleBack}
                      aria-label="Previous step"
                      className={cn(
                        "inline-flex items-center gap-1 px-2.5 py-1 rounded-md",
                        "text-xs font-medium",
                        "text-text-secondary hover:text-text-primary",
                        "hover:bg-surface-hover",
                        "transition-colors duration-150",
                        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                      )}
                    >
                      <ChevronLeft className="h-3 w-3" />
                      Back
                    </button>
                  )}

                  <button
                    type="button"
                    onClick={handleNext}
                    aria-label={isLast ? "Finish tour" : "Next step"}
                    data-testid="tour-next"
                    className={cn(
                      "inline-flex items-center gap-1 px-3 py-1 rounded-md",
                      "text-xs font-medium",
                      "bg-primary-500 text-white hover:bg-primary-600",
                      "transition-colors duration-150",
                      "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                    )}
                  >
                    {isLast ? "Finish" : "Next"}
                    {!isLast && <ChevronRight className="h-3 w-3" />}
                  </button>
                </div>
              </div>
            </motion.div>
          </AnimatePresence>
        </div>
      )}
    </AnimatePresence>
  );
}

export default SpotlightTour;
