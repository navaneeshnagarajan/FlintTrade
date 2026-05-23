/**
 * ContextTipCard — small, non-intrusive education card shown in widget headers.
 *
 * Displays the most relevant undismissed tip for the given trigger.
 * Fades in gently, can be dismissed with "Got it", or navigated to /learn.
 * Respects user skill level and inline-hints preference.
 */

import { useNavigate } from "react-router-dom";
import { motion, AnimatePresence } from "framer-motion";
import { Lightbulb, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { useContextTips } from "@/hooks/useContextTips";
import { motionConfig } from "@/lib/motion";

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

export interface ContextTipCardProps {
  /** Trigger string, e.g. "widget:optionchain" */
  trigger: string;
  /** Optional extra classes on the outer container */
  className?: string;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function difficultyColor(d: "beginner" | "intermediate" | "advanced"): string {
  if (d === "beginner") return "bg-bullish-bg text-profit border-0";
  if (d === "intermediate") return "bg-atm-bg text-warning border-0";
  return "bg-bearish-bg text-loss border-0";
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function ContextTipCard({ trigger, className = "" }: ContextTipCardProps) {
  const { tip, dismiss } = useContextTips(trigger);
  const navigate = useNavigate();

  return (
    <AnimatePresence>
      {tip && (
        <motion.div
          key={tip.id}
          initial={{ opacity: 0, height: 0 }}
          animate={{ opacity: 1, height: "auto" }}
          exit={{ opacity: 0, height: 0 }}
          transition={{
            duration: motionConfig.duration.normal,
            ease: motionConfig.ease.enter,
          }}
          className={`overflow-hidden ${className}`}
        >
          <div className="flex items-start gap-2 bg-surface-card border border-accent/20 rounded-md px-3 py-2 text-xs">
            {/* Icon */}
            <Lightbulb className="w-3.5 h-3.5 text-accent shrink-0 mt-0.5" />

            {/* Content */}
            <div className="flex-1 min-w-0 space-y-1">
              {/* Title row */}
              <div className="flex items-center gap-2">
                <span className="font-semibold text-text-primary truncate">
                  {tip.title}
                </span>
                <Badge className={`text-[10px] px-1.5 py-0 ${difficultyColor(tip.difficulty)}`}>
                  {tip.difficulty}
                </Badge>
              </div>

              {/* Body */}
              <p className="text-text-secondary leading-relaxed line-clamp-3">
                {tip.content}
              </p>

              {/* Actions */}
              <div className="flex items-center gap-2 pt-0.5">
                {tip.learnMoreUrl && (
                  <Button
                    variant="link"
                    size="sm"
                    className="h-auto p-0 text-xs text-accent hover:text-accent/80"
                    onClick={() => navigate(tip.learnMoreUrl!)}
                  >
                    Learn More
                  </Button>
                )}
                {tip.dismissable && (
                  <Button
                    variant="ghost"
                    size="sm"
                    className="h-auto p-0 text-xs text-text-muted hover:text-text-primary"
                    onClick={dismiss}
                  >
                    Got it
                  </Button>
                )}
              </div>
            </div>

            {/* Close button */}
            {tip.dismissable && (
              <button
                type="button"
                onClick={dismiss}
                className="shrink-0 p-0.5 rounded text-text-muted hover:text-text-primary transition-colors"
                aria-label="Dismiss tip"
              >
                <X className="w-3 h-3" />
              </button>
            )}
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}

export default ContextTipCard;
