/**
 * RouteBanner.tsx
 *
 * Dismissible page tip.
 *
 * Behaviour:
 *   - Only renders when `helpPrefs.inlineHints` is true
 *   - Shows a lightbulb icon, hint text, and a dismiss X button
 *   - Dismissed state is persisted in localStorage as
 *     `ft-hint-dismissed-<hintId>` so it never reappears after dismissal
 *   - Dismissed hints can be bulk-reset from Settings (same key pattern
 *     used by InlineHint)
 *
 * Placement: pages render it inside their body, under the page header, as a
 * rounded Callout. The Trade desk uses the slim full-width `strip` variant
 * so the canvas keeps its height.
 */

import { useState } from "react";
import { Lightbulb, X } from "lucide-react";
import { Callout } from "@/components/ui/Callout";
import { useHelpPrefs } from "@/hooks/useHelpPrefs";
import { cn } from "@/lib/utils";

// ---------------------------------------------------------------------------
// localStorage helpers (same key pattern as InlineHint for bulk reset)
// ---------------------------------------------------------------------------

function storageKey(hintId: string): string {
  return `ft-hint-dismissed-${hintId}`;
}

function isDismissed(hintId: string): boolean {
  try {
    return localStorage.getItem(storageKey(hintId)) === "true";
  } catch {
    return false;
  }
}

function persistDismiss(hintId: string): void {
  try {
    localStorage.setItem(storageKey(hintId), "true");
  } catch {
    // Silently ignore — storage might be full or unavailable
  }
}

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

export interface RouteBannerProps {
  /** Unique identifier for dismiss persistence, e.g. "trade-shortcuts" */
  hintId: string;
  /** Hint text displayed in the banner */
  text: string;
  /** Rounded in-page callout (default) or a slim full-width strip. */
  variant?: "callout" | "strip";
  /** Additional class names on the outer wrapper */
  className?: string;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function RouteBanner({ hintId, text, variant = "callout", className }: RouteBannerProps) {
  const helpPrefs = useHelpPrefs();
  const [dismissed, setDismissed] = useState(() => isDismissed(hintId));

  if (!helpPrefs.inlineHints || dismissed) {
    return null;
  }

  function handleDismiss() {
    persistDismiss(hintId);
    setDismissed(true);
  }

  if (variant === "strip") {
    return (
      <div
        role="note"
        aria-label="Hint"
        className={cn(
          "flex shrink-0 items-center gap-2 border-b border-border-default bg-surface-base px-3 py-1.5",
          className,
        )}
      >
        <Lightbulb className="h-3.5 w-3.5 shrink-0 text-accent" aria-hidden="true" />
        <p className="flex-1 text-xs leading-relaxed text-text-secondary">{text}</p>
        <button
          type="button"
          onClick={handleDismiss}
          aria-label="Dismiss hint"
          className="grid size-6 shrink-0 place-items-center rounded-md text-text-muted transition-colors hover:bg-surface-hover hover:text-text-primary"
        >
          <X className="h-3.5 w-3.5" aria-hidden="true" />
        </button>
      </div>
    );
  }

  return (
    <Callout
      tone="tip"
      aria-label="Hint"
      onDismiss={handleDismiss}
      dismissLabel="Dismiss hint"
      className={className}
    >
      {text}
    </Callout>
  );
}

export default RouteBanner;
