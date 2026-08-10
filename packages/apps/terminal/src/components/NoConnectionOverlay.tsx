/**
 * NoConnectionOverlay — global overlay shown after 5s without live broker data.
 *
 * Avoids flashing on startup by waiting 5 seconds before becoming visible.
 * Clears immediately when connection is restored.
 * Rendered inside AppLayout so it covers all app routes.
 *
 * Issue #72 — Suppressed on routes that don't require a live broker connection
 * (/settings, /explore) as a defensive guard against future routing changes.
 *
 * Issue #56 — Focus is trapped inside the dialog while it is visible, satisfying
 * WCAG 2.1 SC 2.1.2 (No Keyboard Trap) and the aria-modal contract.
 */

import { useState, useEffect, useRef, useCallback } from "react";
import { WifiOff, Settings, RefreshCw } from "lucide-react";
import { useNavigate, useLocation } from "react-router";
import { layerClassNames } from "@flinttrade/design-system";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { useConnectionStore } from "@/stores/connectionStore";
import { useModeStore } from "@/stores/modeStore";

const DELAY_MS = 5000;

/**
 * Routes where a live broker data connection is not required.
 * The overlay is suppressed on these paths so users can configure
 * settings or explore demo data without being interrupted.
 */
const SUPPRESSED_ROUTE_PREFIXES = [
  "/settings",
  "/explore",
  "/learn",
  "/invest",
  "/ai",
  "/lab",
  "/automate",
  "/ditto",
  "/admin",
  "/welcome",
  "/setup",
];

/** CSS selector for all keyboard-focusable elements inside the dialog. */
const FOCUSABLE_SELECTOR =
  'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

export function NoConnectionOverlay() {
  const status = useConnectionStore((s) => s.status);
  const mode = useModeStore((s) => s.mode);
  const [showOverlay, setShowOverlay] = useState(false);
  const navigate = useNavigate();
  const location = useLocation();
  const dialogRef = useRef<HTMLDivElement>(null);

  // Issue #72 — Don't interrupt routes that work without a live connection.
  const isSuppressedRoute = SUPPRESSED_ROUTE_PREFIXES.some((prefix) =>
    location.pathname.startsWith(prefix),
  );

  useEffect(() => {
    if (status === "disconnected" && mode === "live" && !isSuppressedRoute) {
      const timer = setTimeout(() => setShowOverlay(true), DELAY_MS);
      return () => clearTimeout(timer);
    }
    // Explore and Practice remain usable without broker data. Only Live mode
    // owns the blocking disconnection gate.
    setShowOverlay(false);
  }, [isSuppressedRoute, mode, status]);

  // Issue #56 — Auto-focus the first interactive element when the overlay opens.
  useEffect(() => {
    if (!showOverlay || isSuppressedRoute) return;

    const dialog = dialogRef.current;
    if (!dialog) return;

    // Delay focus to prevent residual Enter keypress from triggering the focused button
    const timer = setTimeout(() => {
      const firstFocusable = dialog.querySelector<HTMLElement>(FOCUSABLE_SELECTOR);
      firstFocusable?.focus();
    }, 100);
    return () => clearTimeout(timer);
  }, [showOverlay, isSuppressedRoute]);

  // Issue #56 — Tab/Shift+Tab cycles within the dialog only.
  const handleKeyDown = useCallback((e: React.KeyboardEvent<HTMLDivElement>) => {
    if (e.key !== "Tab") return;

    const dialog = dialogRef.current;
    if (!dialog) return;

    const focusable = Array.from(
      dialog.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR),
    ).filter((el) => !el.closest("[aria-hidden='true']"));

    if (focusable.length === 0) return;

    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    const active = document.activeElement as HTMLElement | null;

    if (e.shiftKey) {
      // Shift+Tab — wrap backward from first to last
      if (active === first) {
        e.preventDefault();
        last.focus();
      }
    } else {
      // Tab — wrap forward from last to first
      if (active === last) {
        e.preventDefault();
        first.focus();
      }
    }
  }, []);

  if (!showOverlay || isSuppressedRoute || mode !== "live") return null;

  return (
    <div
      ref={dialogRef}
      role="alertdialog"
      aria-modal="true"
      aria-labelledby="no-connection-title"
      aria-describedby="no-connection-desc"
      onKeyDown={handleKeyDown}
      className={cn(
        "fixed inset-0 bg-surface-base/80 backdrop-blur-sm flex items-center justify-center",
        layerClassNames.modal,
      )}
    >
      <div className="bg-surface-card border border-border-default rounded-xl p-8 max-w-md w-full mx-4 text-center space-y-4 shadow-2xl">
        <div className="flex justify-center">
          <div className="w-14 h-14 rounded-full bg-loss/10 border border-loss/20 flex items-center justify-center">
            <WifiOff className="w-6 h-6 text-loss" aria-hidden="true" />
          </div>
        </div>

        <div className="space-y-1.5">
          <h2
            id="no-connection-title"
            className="text-lg font-heading font-semibold text-text-primary"
          >
            Live Broker Data Disconnected
          </h2>
          <p
            id="no-connection-desc"
            className="text-sm text-text-secondary leading-relaxed"
          >
            Cannot reach the configured broker gateway. Check your OpenAlgo
            bridge or verified native broker settings, then retry.
          </p>
        </div>

        <div className="flex gap-3 justify-center pt-1">
          <Button
            variant="outline"
            size="sm"
            onClick={() => { setShowOverlay(false); navigate("/settings#api"); }}
          >
            <Settings className="w-3.5 h-3.5 mr-1.5" />
            Settings
          </Button>
          <Button
            size="sm"
            onClick={() => window.location.reload()}
          >
            <RefreshCw className="w-3.5 h-3.5 mr-1.5" />
            Retry
          </Button>
        </div>

      </div>
    </div>
  );
}
