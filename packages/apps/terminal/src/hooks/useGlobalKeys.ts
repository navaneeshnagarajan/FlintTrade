import { useEffect } from "react";
import { cancelAllOrders, closePosition } from "@/services/api";
import { emitNotification } from "@/components/NotificationCentre/useNotificationFeed";

interface GlobalKeyHandlers {
  onEscape?: () => void;
  onCommandPalette?: () => void;
  /** Fired when `?` is pressed with no input focused — opens the shortcuts dialog. */
  onShowShortcuts?: () => void;
}

/**
 * Destructive trading hotkeys (exit-all / cancel-all) must run exactly once per
 * keypress. The hook is mounted by more than one layout level (AppLayout wraps
 * TerminalRoute on /trade), so each keydown reaches multiple listeners. Each
 * listener marks the event here before acting; later listeners skip it. The
 * callback keys (Escape, Ctrl+K, ?) are NOT deduplicated — each mount point
 * passes its own handlers and expects them to fire.
 */
const handledTradingKeyEvents = new WeakSet<KeyboardEvent>();

function reportTradingActionFailure(title: string, err: unknown): void {
  const body = err instanceof Error ? err.message : "Unknown error — check the broker connection.";
  console.error(`[GlobalKeys] ${title}:`, err);
  // Surface the failure to the operator — a silent failed emergency exit is
  // worse than no hotkey at all (the trader believes they are flat).
  emitNotification({ category: "order", title, body });
}

/**
 * Global keyboard shortcuts for FlintTrade terminal.
 * Only fires when no input/textarea is focused.
 *
 * Shortcuts:
 *   Ctrl+K       -- Command palette
 *   X / Shift+X  -- Exit all positions (confirmation required)
 *   C            -- Cancel all orders (confirmation required)
 *   Esc          -- Close active tool/modal
 *   ?            -- Show keyboard shortcuts reference dialog
 *   F1-F8        -- Reserved for widget focus (future)
 */
export default function useGlobalKeys({
  onEscape,
  onCommandPalette,
  onShowShortcuts,
}: GlobalKeyHandlers): void {
  useEffect(() => {
    function handler(e: KeyboardEvent): void {
      // Skip if user is typing in an input or has a button/link focused
      const tag = document.activeElement?.tagName;
      if (
        tag === "INPUT" ||
        tag === "TEXTAREA" ||
        tag === "SELECT" ||
        tag === "BUTTON" ||
        tag === "A"
      ) return;
      if ((document.activeElement as HTMLElement)?.isContentEditable) return;

      // Ctrl+K -- Command palette
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        onCommandPalette?.();
        return;
      }

      // Esc -- Close tool/modal
      if (e.key === "Escape") {
        e.preventDefault();
        onEscape?.();
        return;
      }

      // ? -- Show keyboard shortcuts dialog
      if (e.key === "?" && !e.ctrlKey && !e.metaKey && !e.altKey) {
        e.preventDefault();
        onShowShortcuts?.();
        return;
      }

      // X / Shift+X -- Exit all positions (confirmation required).
      // The /trade banner advertises plain X, so both variants behave the same.
      if ((e.key === "x" || e.key === "X") && !e.ctrlKey && !e.metaKey && !e.altKey) {
        if (handledTradingKeyEvents.has(e)) return;
        handledTradingKeyEvents.add(e);
        if (window.confirm("Close ALL open positions? This cannot be undone.")) {
          closePosition("Flint")
            .then(() =>
              emitNotification({
                category: "order",
                title: "Exit all positions requested",
                body: "Close request sent for all open positions.",
              }),
            )
            .catch((err) => reportTradingActionFailure("Exit all positions failed", err));
        }
        return;
      }

      // C -- Cancel all orders (requires confirmation)
      if (e.key === "c" || e.key === "C") {
        if (!e.ctrlKey && !e.metaKey) {
          if (handledTradingKeyEvents.has(e)) return;
          handledTradingKeyEvents.add(e);
          if (window.confirm("Cancel ALL open orders? This cannot be undone.")) {
            cancelAllOrders()
              .then(() =>
                emitNotification({
                  category: "order",
                  title: "Cancel all orders requested",
                  body: "Cancel request sent for all open orders.",
                }),
              )
              .catch((err) => reportTradingActionFailure("Cancel all orders failed", err));
          }
          return;
        }
      }
    }

    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [onEscape, onCommandPalette, onShowShortcuts]);
}
