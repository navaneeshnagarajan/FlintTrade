/**
 * UpgradeSuggestion — upgrade prompt toast.
 *
 * Shows at the bottom-left to avoid colliding with the AITutorPill (bottom-right).
 * Displays one suggestion at a time; queues the rest.
 *
 * Buttons:
 *   [Upgrade]        — applies the suggested level override and dismisses
 *   [Not now]        — hides for this session (will show next reload)
 *   [Don't ask again] — permanently dismisses via skillStore.dismissSuggestion()
 *
 * Wiring:
 *   Mount <UpgradeSuggestionHost /> in RootLayout or AppLayout.
 *   It polls skillStore.getSuggestions() every 60 seconds.
 */

import { useState, useEffect, useCallback, useRef } from "react";
import { AnimatePresence, motion } from "framer-motion";
import {
  TrendingUp,
  PiggyBank,
  BookOpen,
  FlaskConical,
  Workflow,
  Bot,
  ArrowUpCircle,
  X,
  type LucideIcon,
} from "lucide-react";
import { useSkillStore } from "@/stores/skillStore";
import type { UpgradeSuggestion as UpgradeSuggestionType } from "@/types/skill";
import type { Domain } from "@/types/skill";
import { motionConfig, DURATION, EASE_ENTER, EASE_EXIT } from "@/lib/motion";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const POLL_INTERVAL_MS = 60_000;

// ---------------------------------------------------------------------------
// Domain icon map
// ---------------------------------------------------------------------------

const DOMAIN_ICONS: Record<Domain, LucideIcon> = {
  trade:    TrendingUp,
  invest:   PiggyBank,
  learn:    BookOpen,
  lab:      FlaskConical,
  automate: Workflow,
  ai:       Bot,
};

const DOMAIN_LABELS: Record<Domain, string> = {
  trade:    "Trade",
  invest:   "Invest",
  learn:    "Learn",
  lab:      "Lab",
  automate: "Automate",
  ai:       "AI",
};

const LEVEL_LABELS: Record<string, string> = {
  beginner:     "Getting Started",
  intermediate: "Confident",
  advanced:     "Expert",
};

// ---------------------------------------------------------------------------
// Single toast card
// ---------------------------------------------------------------------------

interface UpgradeSuggestionCardProps {
  suggestion: UpgradeSuggestionType;
  onUpgrade: () => void;
  onNotNow: () => void;
  onDontAsk: () => void;
}

function UpgradeSuggestionCard({
  suggestion,
  onUpgrade,
  onNotNow,
  onDontAsk,
}: UpgradeSuggestionCardProps) {
  const reduced = motionConfig.prefersReducedMotion();
  const Icon = DOMAIN_ICONS[suggestion.domain];
  const toLabel = LEVEL_LABELS[suggestion.toLevel] ?? suggestion.toLevel;
  const domainLabel = DOMAIN_LABELS[suggestion.domain];

  return (
    <motion.div
      role="alertdialog"
      aria-labelledby="upgrade-suggestion-title"
      aria-describedby="upgrade-suggestion-desc"
      className="w-80 rounded-xl border border-border-default bg-surface-card shadow-2xl overflow-hidden"
      initial={reduced ? { opacity: 0 } : { opacity: 0, y: 16, scale: 0.97 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      exit={reduced ? { opacity: 0 } : { opacity: 0, y: 12, scale: 0.96 }}
      transition={{ duration: DURATION.normal, ease: EASE_ENTER }}
    >
      {/* Thin accent bar at the top */}
      <div className="h-0.5 w-full bg-gradient-to-r from-accent/60 via-accent to-accent/60" />

      {/* Body */}
      <div className="px-4 py-3 space-y-3">
        {/* Header row */}
        <div className="flex items-start gap-2.5">
          <div className="mt-0.5 w-7 h-7 rounded-lg bg-accent/10 flex items-center justify-center shrink-0">
            <Icon size={14} className="text-accent" />
          </div>
          <div className="flex-1 min-w-0">
            <p
              id="upgrade-suggestion-title"
              className="text-xs font-semibold text-text-primary leading-snug"
            >
              Ready for <span className="text-accent">{toLabel}</span> in {domainLabel}?
            </p>
            <p
              id="upgrade-suggestion-desc"
              className="text-xs text-text-muted mt-0.5 leading-relaxed"
            >
              {suggestion.reason}
            </p>
          </div>
          <button
            type="button"
            onClick={onNotNow}
            aria-label="Dismiss for now"
            className="h-5 w-5 flex items-center justify-center rounded text-text-muted hover:text-text-primary hover:bg-surface-hover transition-colors shrink-0 mt-0.5"
          >
            <X size={12} />
          </button>
        </div>

        {/* Action buttons */}
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={onUpgrade}
            className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg bg-accent text-white hover:bg-accent/90 transition-colors"
          >
            <ArrowUpCircle size={12} />
            Upgrade
          </button>
          <button
            type="button"
            onClick={onNotNow}
            className="px-3 py-1.5 text-xs text-text-secondary hover:text-text-primary rounded-lg hover:bg-surface-hover transition-colors"
          >
            Not now
          </button>
          <button
            type="button"
            onClick={onDontAsk}
            className="ml-auto px-2 py-1.5 text-xs text-text-muted hover:text-text-secondary rounded-lg hover:bg-surface-hover transition-colors"
          >
            Don't ask again
          </button>
        </div>
      </div>
    </motion.div>
  );
}

// ---------------------------------------------------------------------------
// UpgradeSuggestionHost — mounts in RootLayout
// ---------------------------------------------------------------------------

export function UpgradeSuggestionHost() {
  const setRouteOverride   = useSkillStore((s) => s.setRouteOverride);
  const dismissSuggestion  = useSkillStore((s) => s.dismissSuggestion);
  const getSuggestions     = useSkillStore((s) => s.getSuggestions);

  // The current active toast
  const [activeSuggestion, setActiveSuggestion] = useState<UpgradeSuggestionType | null>(null);
  // Session-level dismissals (not persisted — will show next reload)
  const sessionDismissed   = useRef<Set<string>>(new Set());
  // Ref to avoid re-creating refresh when activeSuggestion changes (prevents interval reset)
  const activeSuggestionRef = useRef(activeSuggestion);
  useEffect(() => { activeSuggestionRef.current = activeSuggestion; }, [activeSuggestion]);

  const refresh = useCallback(() => {
    if (activeSuggestionRef.current) return; // don't interrupt an active toast
    const all = getSuggestions();
    const next = all.find(
      (s) => !sessionDismissed.current.has(`${s.domain}:${s.toLevel}`),
    );
    setActiveSuggestion(next ?? null);
  }, [getSuggestions]);

  // Initial check after mount, then every 60s
  useEffect(() => {
    // Slight delay so we don't show on first render before the user settles
    const initial = setTimeout(refresh, 3000);
    const interval = setInterval(refresh, POLL_INTERVAL_MS);
    return () => {
      clearTimeout(initial);
      clearInterval(interval);
    };
  }, [refresh]);

  const handleUpgrade = useCallback(() => {
    if (!activeSuggestion) return;
    setRouteOverride(activeSuggestion.domain, activeSuggestion.toLevel);
    dismissSuggestion(`${activeSuggestion.domain}:${activeSuggestion.toLevel}`);
    sessionDismissed.current.add(`${activeSuggestion.domain}:${activeSuggestion.toLevel}`);
    setActiveSuggestion(null);
  }, [activeSuggestion, setRouteOverride, dismissSuggestion]);

  const handleNotNow = useCallback(() => {
    if (!activeSuggestion) return;
    sessionDismissed.current.add(`${activeSuggestion.domain}:${activeSuggestion.toLevel}`);
    setActiveSuggestion(null);
  }, [activeSuggestion]);

  const handleDontAsk = useCallback(() => {
    if (!activeSuggestion) return;
    dismissSuggestion(`${activeSuggestion.domain}:${activeSuggestion.toLevel}`);
    sessionDismissed.current.add(`${activeSuggestion.domain}:${activeSuggestion.toLevel}`);
    setActiveSuggestion(null);
  }, [activeSuggestion, dismissSuggestion]);

  return (
    <div
      className="fixed bottom-4 left-4 z-50 hidden sm:block"
      aria-live="polite"
      aria-atomic="true"
    >
      <AnimatePresence mode="wait">
        {activeSuggestion && (
          <motion.div
            key={`${activeSuggestion.domain}:${activeSuggestion.toLevel}`}
            initial={{ opacity: 0, y: 16 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: 12 }}
            transition={{ duration: DURATION.normal, ease: EASE_EXIT }}
          >
            <UpgradeSuggestionCard
              suggestion={activeSuggestion}
              onUpgrade={handleUpgrade}
              onNotNow={handleNotNow}
              onDontAsk={handleDontAsk}
            />
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

export default UpgradeSuggestionHost;
