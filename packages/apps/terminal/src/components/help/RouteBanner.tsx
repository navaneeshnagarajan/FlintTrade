/**
 * RouteBanner.tsx
 *
 * Dismissible hint banner rendered at the top of a route.
 *
 * Behaviour:
 *   - Only renders when `helpPrefs.inlineHints` is true
 *   - Shows a lightbulb icon, hint text, and a dismiss X button
 *   - Dismissed state is persisted in localStorage as
 *     `flinttrade:hint:<hintId>` so it never reappears after dismissal
 *   - Dismissed hints can be bulk-reset from Settings (same key pattern
 *     used by InlineHint: `ft-hint-dismissed-<hintId>`)
 *
 * Design:
 *   - Accent-tinted glass surface, consistent with FlintTrade design tokens
 *   - Respects prefers-reduced-motion (no animation when reduced)
 */

import { useState } from "react";
import { Lightbulb, X } from "lucide-react";
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
  /** Additional class names on the outer wrapper */
  className?: string;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function RouteBanner({ hintId, text, className }: RouteBannerProps) {
  const helpPrefs = useHelpPrefs();
  const [dismissed, setDismissed] = useState(() => isDismissed(hintId));

  if (!helpPrefs.inlineHints || dismissed) {
    return null;
  }

  function handleDismiss() {
    persistDismiss(hintId);
    setDismissed(true);
  }

  return (
    <div
      role="note"
      aria-label="Hint"
      className={cn(
        "flex items-center gap-2 px-4 py-2",
        "border-b border-accent/20 bg-accent/5",
        "shrink-0",
        className,
      )}
    >
      <Lightbulb
        className="h-3.5 w-3.5 shrink-0 text-accent"
        aria-hidden="true"
      />
      <p className="flex-1 text-xs text-text-secondary leading-relaxed">
        {text}
      </p>
      <button
        type="button"
        onClick={handleDismiss}
        aria-label="Dismiss hint"
        className={cn(
          "shrink-0 h-5 w-5 rounded flex items-center justify-center",
          "text-text-muted hover:text-text-primary",
          "transition-colors duration-150",
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
        )}
      >
        <X className="h-3 w-3" />
      </button>
    </div>
  );
}

export default RouteBanner;
