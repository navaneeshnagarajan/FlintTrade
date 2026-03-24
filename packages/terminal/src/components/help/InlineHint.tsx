/**
 * InlineHint.tsx
 *
 * A small "?" icon that shows a glassmorphism tooltip on hover/click.
 * Used next to any field or label to explain what it does.
 *
 * Behaviour:
 *   - Only renders the "?" icon when `helpPrefs.inlineHints` is true
 *   - Hover / click shows a glass-styled popover with the hint text
 *   - Dismissible: clicking the X stores `ft-hint-dismissed-{featureId}` in
 *     localStorage so the same hint never shows again
 *   - Dismissed hints can be bulk-reset from Settings
 *   - Framer Motion: fade-in for tooltip (200ms, EASE_ENTER)
 *   - WCAG: tooltip content accessible to screen readers, Escape closes
 *
 * Layout:
 *   - Renders children inline with a superscript "?" button after them
 *   - Popover positioned via Radix (auto-flips to avoid overflow)
 *   - Glass effect: backdrop-blur + semi-transparent bg matching theme
 */

import { useState, useCallback } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { HelpCircle, X } from "lucide-react";
import {
  Popover,
  PopoverTrigger,
  PopoverContent,
} from "@/components/ui/popover";
import { useHelpPrefs } from "@/hooks/useHelpPrefs";
import { DURATION, EASE_ENTER, EASE_EXIT } from "@/lib/motion";
import { cn } from "@/lib/utils";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface InlineHintProps {
  /** The hint / explanation text shown in the tooltip */
  text: string;
  /** The label or field element that the hint is attached to */
  children: React.ReactNode;
  /**
   * Unique identifier for dismiss persistence.
   * When provided, dismissing the hint stores
   * `ft-hint-dismissed-{featureId}` in localStorage.
   */
  featureId?: string;
  /** Additional class names on the wrapper span */
  className?: string;
}

// ---------------------------------------------------------------------------
// localStorage helpers
// ---------------------------------------------------------------------------

function storageKey(featureId: string): string {
  return `ft-hint-dismissed-${featureId}`;
}

function isDismissed(featureId: string | undefined): boolean {
  if (!featureId) return false;
  try {
    return localStorage.getItem(storageKey(featureId)) === "true";
  } catch {
    return false;
  }
}

function persistDismiss(featureId: string): void {
  try {
    localStorage.setItem(storageKey(featureId), "true");
  } catch {
    // Silently ignore — storage might be full or unavailable
  }
}

// ---------------------------------------------------------------------------
// Animation variants
// ---------------------------------------------------------------------------

const tooltipVariants = {
  initial: { opacity: 0, scale: 0.96 },
  animate: {
    opacity: 1,
    scale: 1,
    transition: { duration: DURATION.normal, ease: EASE_ENTER },
  },
  exit: {
    opacity: 0,
    scale: 0.96,
    transition: { duration: DURATION.fast, ease: EASE_EXIT },
  },
};

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function InlineHint({
  text,
  children,
  featureId,
  className,
}: InlineHintProps) {
  const helpPrefs = useHelpPrefs();
  const [dismissed, setDismissed] = useState(() => isDismissed(featureId));
  const [open, setOpen] = useState(false);

  const handleDismiss = useCallback(() => {
    if (featureId) {
      persistDismiss(featureId);
      setDismissed(true);
    }
    setOpen(false);
  }, [featureId]);

  // Do not render the "?" icon when hints are globally disabled or dismissed
  const showIcon = helpPrefs.inlineHints && !dismissed;

  return (
    <span className={cn("inline-flex items-center gap-1", className)}>
      {children}

      {showIcon && (
        <Popover open={open} onOpenChange={setOpen}>
          <PopoverTrigger asChild>
            <button
              type="button"
              aria-label="Show hint"
              className={cn(
                "inline-flex items-center justify-center",
                "h-4 w-4 rounded-full",
                "text-text-muted hover:text-text-secondary",
                "transition-colors duration-150",
                "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                "cursor-help",
              )}
            >
              <HelpCircle className="h-3.5 w-3.5" />
            </button>
          </PopoverTrigger>

          <AnimatePresence>
            {open && (
              <PopoverContent
                asChild
                sideOffset={6}
                className="w-auto max-w-[240px] p-0 border-0 bg-transparent shadow-none"
              >
                <motion.div
                  variants={tooltipVariants}
                  initial="initial"
                  animate="animate"
                  exit="exit"
                  role="tooltip"
                  className={cn(
                    "rounded-lg px-3 py-2.5",
                    "border border-border-default/50",
                    "bg-surface-card/80",
                    "text-xs text-text-secondary leading-relaxed",
                    "shadow-lg",
                  )}
                  style={{
                    backdropFilter: "blur(12px)",
                    WebkitBackdropFilter: "blur(12px)",
                  }}
                >
                  <div className="flex items-start gap-2">
                    <p className="flex-1">{text}</p>
                    {featureId && (
                      <button
                        type="button"
                        onClick={handleDismiss}
                        aria-label="Dismiss hint"
                        className={cn(
                          "shrink-0 h-4 w-4 rounded",
                          "text-text-muted hover:text-text-primary",
                          "transition-colors duration-150",
                          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                        )}
                      >
                        <X className="h-3 w-3" />
                      </button>
                    )}
                  </div>
                </motion.div>
              </PopoverContent>
            )}
          </AnimatePresence>
        </Popover>
      )}
    </span>
  );
}

export default InlineHint;
