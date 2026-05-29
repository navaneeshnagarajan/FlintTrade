/**
 * PreviewBanner.tsx
 *
 * A compact, dismissible glassmorphism banner displayed at the top of a
 * teaser overlay. Shows the feature name, status badge, and optional
 * version target.
 *
 * Glass mode is driven by `themeStore.glass.enabled` so it follows the
 * user's global glass preference. Dismissed state is stored in
 * localStorage so it persists across page reloads.
 *
 * Framer Motion: fades in from y -10 → 0. Fades out upward on dismiss.
 * Respects `prefers-reduced-motion` via motionConfig.prefersReducedMotion().
 */

import { useState, useEffect } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Eye, Code, TestTube, Zap, X } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { useShallow } from "zustand/react/shallow";
import { useThemeStore } from "@/stores/themeStore";
import { cn } from "@/lib/utils";
import { motionConfig, EASE_ENTER, DURATION } from "@/lib/motion";
import type { FeatureStatus, TeaserConfig } from "./types";
import { STATUS_LABELS, STATUS_COLORS } from "./types";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const DISMISSED_KEY = "ft-teaser-dismissed";

const STATUS_ICONS: Record<FeatureStatus, LucideIcon> = {
  preview: Eye,
  in_dev: Code,
  testing: TestTube,
  live: Zap,
};

// ---------------------------------------------------------------------------
// Helper — localStorage dismissed set
// ---------------------------------------------------------------------------

function getDismissedSet(): Set<string> {
  try {
    const raw = localStorage.getItem(DISMISSED_KEY);
    const parsed: unknown = raw ? JSON.parse(raw) : [];
    if (Array.isArray(parsed)) {
      return new Set(parsed as string[]);
    }
  } catch {
    // ignore parse errors
  }
  return new Set<string>();
}

function saveDismissedSet(set: Set<string>): void {
  try {
    localStorage.setItem(DISMISSED_KEY, JSON.stringify(Array.from(set)));
  } catch {
    // ignore storage quota errors
  }
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

interface PreviewBannerProps {
  config: TeaserConfig;
  className?: string;
}

export function PreviewBanner({ config, className }: PreviewBannerProps) {
  const { featureName, status, version } = config;

  // Dismissed state initialised from localStorage to avoid flash
  const [dismissed, setDismissed] = useState<boolean>(() => {
    return getDismissedSet().has(featureName);
  });

  // Glass toggle from theme store (boolean in v4)
  const glassEnabled = useThemeStore(
    useShallow((state) => state.glass),
  );

  const StatusIcon = STATUS_ICONS[status];
  const label = STATUS_LABELS[status];
  const colorClass = STATUS_COLORS[status];

  const reduceMotion = motionConfig.prefersReducedMotion();

  // Sync dismissed to localStorage whenever it changes
  useEffect(() => {
    if (dismissed) {
      const set = getDismissedSet();
      set.add(featureName);
      saveDismissedSet(set);
    }
  }, [dismissed, featureName]);

  const bannerVariants: import("framer-motion").Variants = {
    initial: reduceMotion ? { opacity: 0 } : { opacity: 0, y: -10 },
    animate: reduceMotion
      ? { opacity: 1, transition: { duration: DURATION.fast } }
      : {
          opacity: 1,
          y: 0,
          transition: {
            duration: DURATION.normal,
            ease: EASE_ENTER as [number, number, number, number],
          },
        },
    exit: reduceMotion
      ? { opacity: 0, transition: { duration: DURATION.fast } }
      : {
          opacity: 0,
          y: -8,
          transition: {
            duration: DURATION.fast,
            ease: [0.4, 0, 1, 1] as [number, number, number, number],
          },
        },
  };

  // Glass styles via inline CSS (dynamic values from store — cannot be
  // resolved at build time by Tailwind's static scanner)
  const glassStyle: React.CSSProperties = glassEnabled
    ? {
        backdropFilter: "blur(12px)",
        WebkitBackdropFilter: "blur(12px)",
        background: "var(--glass-l2-bg, var(--color-surface-elevated))",
        border: "1px solid var(--glass-l2-border, var(--color-border-default))",
      }
    : {};

  return (
    <AnimatePresence>
      {!dismissed && (
        <motion.div
          key={`preview-banner-${featureName}`}
          variants={bannerVariants}
          initial="initial"
          animate="animate"
          exit="exit"
          role="status"
          aria-label={`${featureName} — ${label}`}
          className={cn(
            "flex items-center gap-2 rounded-md px-3 py-1.5 text-xs",
            glassEnabled
              ? ""
              : "bg-surface-card border border-border-default",
            className,
          )}
          style={glassStyle}
        >
          {/* Status icon */}
          <StatusIcon
            size={12}
            className={cn("shrink-0", colorClass)}
            aria-hidden="true"
          />

          {/* Feature name */}
          <span className="text-text-primary font-medium truncate">
            {featureName}
          </span>

          {/* Status badge */}
          <span
            className={cn(
              "shrink-0 rounded px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-wider",
              colorClass,
              "bg-current/10",
            )}
          >
            {label}
          </span>

          {/* Version target */}
          {version && (
            <span className="shrink-0 text-text-muted font-mono">
              {version}
            </span>
          )}

          {/* Dismiss */}
          <button
            type="button"
            aria-label="Dismiss banner"
            onClick={() => setDismissed(true)}
            className={cn(
              "ml-auto shrink-0 rounded p-0.5",
              "text-text-muted hover:text-text-primary",
              "focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring",
              "transition-colors duration-100",
            )}
          >
            <X size={12} aria-hidden="true" />
          </button>
        </motion.div>
      )}
    </AnimatePresence>
  );
}

export default PreviewBanner;
