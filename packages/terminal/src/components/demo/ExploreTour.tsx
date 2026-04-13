/**
 * SpotlightTour — lightweight CSS-only spotlight overlay tour.
 * No external tour library dependencies. Uses a CSS clip-path cutout
 * technique to highlight a DOM element while dimming the rest.
 *
 * Usage:
 *   <SpotlightTour steps={STEPS} onComplete={() => setTourDone(true)} />
 *
 * localStorage key: "ft_explore_tour_done"
 */

import { useState, useLayoutEffect, useRef } from "react";
import { createPortal } from "react-dom";
import { Button } from "@/components/ui/button";
import { X, ArrowRight, CheckCircle2 } from "lucide-react";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface TourStep {
  /** CSS selector for the element to spotlight. Use null to show centred. */
  target: string | null;
  title: string;
  description: string;
  /** Where to place the tooltip relative to the spotlight box */
  placement?: "top" | "bottom" | "left" | "right";
}

interface Props {
  steps: TourStep[];
  onComplete: () => void;
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const STORAGE_KEY = "ft_explore_tour_done";
const PADDING = 12; // px padding around spotlight rect

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

interface Rect {
  top: number;
  left: number;
  width: number;
  height: number;
}

function getTargetRect(selector: string | null): Rect | null {
  if (!selector) return null;
  const el = document.querySelector(selector);
  if (!el) return null;
  const r = el.getBoundingClientRect();
  return {
    top: r.top - PADDING,
    left: r.left - PADDING,
    width: r.width + PADDING * 2,
    height: r.height + PADDING * 2,
  };
}

function computeTooltipStyle(
  rect: Rect | null,
  placement: TourStep["placement"],
): React.CSSProperties {
  if (!rect) {
    // Centred fallback
    return {
      position: "fixed",
      top: "50%",
      left: "50%",
      transform: "translate(-50%, -50%)",
    };
  }

  const TOOLTIP_W = 280;
  const TOOLTIP_GAP = 14;

  switch (placement) {
    case "top":
      return {
        position: "fixed",
        bottom: window.innerHeight - rect.top + TOOLTIP_GAP,
        left: Math.max(8, Math.min(rect.left + rect.width / 2 - TOOLTIP_W / 2, window.innerWidth - TOOLTIP_W - 8)),
        width: TOOLTIP_W,
      };
    case "left":
      return {
        position: "fixed",
        top: rect.top + rect.height / 2 - 60,
        right: window.innerWidth - rect.left + TOOLTIP_GAP,
        width: TOOLTIP_W,
      };
    case "right":
      return {
        position: "fixed",
        top: rect.top + rect.height / 2 - 60,
        left: rect.left + rect.width + TOOLTIP_GAP,
        width: TOOLTIP_W,
      };
    case "bottom":
    default:
      return {
        position: "fixed",
        top: rect.top + rect.height + TOOLTIP_GAP,
        left: Math.max(8, Math.min(rect.left + rect.width / 2 - TOOLTIP_W / 2, window.innerWidth - TOOLTIP_W - 8)),
        width: TOOLTIP_W,
      };
  }
}

// ---------------------------------------------------------------------------
// SpotlightTour
// ---------------------------------------------------------------------------

export default function SpotlightTour({ steps, onComplete }: Props) {
  const [step, setStep] = useState(0);
  const [rect, setRect] = useState<Rect | null>(null);
  const rafRef = useRef<number | null>(null);

  const current = steps[step];

  // Measure target element on step change and on scroll/resize
  useLayoutEffect(() => {
    const measure = () => {
      setRect(getTargetRect(current.target));
    };
    measure();

    // Scroll target into view if needed
    if (current.target) {
      const el = document.querySelector(current.target);
      el?.scrollIntoView({ behavior: "smooth", block: "nearest" });
    }

    const onUpdate = () => {
      if (rafRef.current !== null) cancelAnimationFrame(rafRef.current);
      rafRef.current = requestAnimationFrame(measure);
    };

    window.addEventListener("resize", onUpdate);
    window.addEventListener("scroll", onUpdate, true);
    return () => {
      window.removeEventListener("resize", onUpdate);
      window.removeEventListener("scroll", onUpdate, true);
      if (rafRef.current !== null) cancelAnimationFrame(rafRef.current);
    };
  }, [step, current.target]);

  const handleNext = () => {
    if (step < steps.length - 1) {
      setStep((s) => s + 1);
    } else {
      handleComplete();
    }
  };

  const handleComplete = () => {
    localStorage.setItem(STORAGE_KEY, "1");
    onComplete();
  };

  const isLast = step === steps.length - 1;

  // Build the clip-path that cuts a hole around the highlighted element.
  // Uses SVG-based clip-path via inset() for border-radius + smooth fallback.
  const overlayStyle: React.CSSProperties = rect
    ? {
        background: "rgba(0,0,0,0.7)",
        clipPath: `polygon(
          0% 0%, 100% 0%, 100% 100%, 0% 100%,
          0% ${rect.top}px,
          ${rect.left}px ${rect.top}px,
          ${rect.left}px ${rect.top + rect.height}px,
          ${rect.left + rect.width}px ${rect.top + rect.height}px,
          ${rect.left + rect.width}px ${rect.top}px,
          0% ${rect.top}px
        )`,
      }
    : { background: "rgba(0,0,0,0.7)" };

  const tooltipStyle = computeTooltipStyle(rect, current.placement ?? "bottom");

  return createPortal(
    <div
      role="dialog"
      aria-modal="true"
      aria-label={`Tour step ${step + 1} of ${steps.length}: ${current.title}`}
    >
      {/* Dimmed overlay with spotlight cutout */}
      <div
        className="fixed inset-0 z-900 pointer-events-auto transition-[clip-path] duration-300"
        style={overlayStyle}
        onClick={handleNext}
        aria-hidden="true"
      />

      {/* Spotlight border ring */}
      {rect && (
        <div
          className="fixed z-901 rounded-xl pointer-events-none transition-all duration-300"
          style={{
            top: rect.top,
            left: rect.left,
            width: rect.width,
            height: rect.height,
            boxShadow: "0 0 0 2px hsl(var(--primary))",
          }}
          aria-hidden="true"
        />
      )}

      {/* Tooltip */}
      <div
        className="fixed z-902 bg-surface-card border border-border-default rounded-xl shadow-2xl p-4 pointer-events-auto"
        style={tooltipStyle}
      >
        {/* Step indicator + close */}
        <div className="flex items-center justify-between mb-2">
          <div className="flex items-center gap-1.5">
            {steps.map((_, i) => (
              <div
                key={i}
                className={[
                  "w-1.5 h-1.5 rounded-full transition-colors duration-200",
                  i === step ? "bg-primary" : "bg-border-default",
                ].join(" ")}
              />
            ))}
          </div>
          <Button variant="ghost" size="icon" onClick={handleComplete} className="h-5 w-5 text-text-muted hover:text-text-primary" aria-label="Skip tour">
            <X size={13} />
          </Button>
        </div>

        {/* Content */}
        <h3 className="font-heading font-semibold text-sm text-text-primary mb-1">
          {current.title}
        </h3>
        <p className="text-xs text-text-secondary leading-relaxed mb-3">
          {current.description}
        </p>

        {/* Actions */}
        <div className="flex items-center justify-between gap-2">
          <Button
            variant="ghost"
            size="sm"
            className="text-xs text-text-muted h-7 px-2"
            onClick={handleComplete}
          >
            Skip
          </Button>
          <Button
            size="sm"
            className="text-xs h-7 px-3 bg-primary hover:bg-primary/90 text-white"
            onClick={handleNext}
          >
            {isLast ? (
              <>
                <CheckCircle2 size={12} className="mr-1.5" />
                Done
              </>
            ) : (
              <>
                Next
                <ArrowRight size={12} className="ml-1.5" />
              </>
            )}
          </Button>
        </div>
      </div>
    </div>,
    document.body,
  );
}

// ---------------------------------------------------------------------------
// Tour completion check
// ---------------------------------------------------------------------------

export function hasCompletedExploreTour(): boolean {
  try {
    return localStorage.getItem(STORAGE_KEY) === "1";
  } catch {
    return false;
  }
}
