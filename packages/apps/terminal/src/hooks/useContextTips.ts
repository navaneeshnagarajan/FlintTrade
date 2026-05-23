/**
 * useContextTips — returns the most relevant undismissed tip for a trigger.
 *
 * Checks the user's skill level (via skillStore) to filter tips by difficulty.
 * Dismissed tips are tracked in localStorage under "flinttrade:dismissed-tips".
 */

import { useState, useCallback, useMemo } from "react";
import { useSkillStore } from "@/stores/skillStore";
import {
  getTipsForTrigger,
  filterTipsByLevel,
  type ContextTip,
} from "@/lib/contextTips";

// ---------------------------------------------------------------------------
// localStorage key
// ---------------------------------------------------------------------------

const STORAGE_KEY = "flinttrade:dismissed-tips";

// ---------------------------------------------------------------------------
// Helpers — read / write dismissed set from localStorage
// ---------------------------------------------------------------------------

function readDismissed(): Set<string> {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return new Set();
    const parsed: unknown = JSON.parse(raw);
    if (Array.isArray(parsed)) return new Set(parsed as string[]);
    return new Set();
  } catch {
    return new Set();
  }
}

function writeDismissed(ids: Set<string>): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify([...ids]));
  } catch {
    // localStorage full or unavailable — silently ignore
  }
}

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

export interface UseContextTipsResult {
  /** The next undismissed, level-appropriate tip for this trigger, or null */
  tip: ContextTip | null;
  /** Dismiss the current tip (persists to localStorage) */
  dismiss: () => void;
}

export function useContextTips(trigger: string): UseContextTipsResult {
  const globalLevel = useSkillStore((s) => s.globalLevel);
  const helpPrefs = useSkillStore((s) => s.helpPrefs);

  // Track dismissed IDs in state so the component re-renders on dismiss
  const [dismissed, setDismissed] = useState<Set<string>>(readDismissed);

  const tip = useMemo<ContextTip | null>(() => {
    // Respect the inline hints preference
    if (!helpPrefs.inlineHints) return null;

    const allForTrigger = getTipsForTrigger(trigger);
    const levelFiltered = filterTipsByLevel(allForTrigger, globalLevel);
    const undismissed = levelFiltered.filter((t) => !dismissed.has(t.id));
    return undismissed[0] ?? null;
  }, [trigger, globalLevel, helpPrefs.inlineHints, dismissed]);

  const dismiss = useCallback(() => {
    if (!tip) return;
    setDismissed((prev) => {
      const next = new Set(prev);
      next.add(tip.id);
      writeDismissed(next);
      return next;
    });
  }, [tip]);

  return { tip, dismiss };
}
