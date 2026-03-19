import { useEffect } from "react";
import { cancelAllOrders, closePosition } from "@/services/api";

interface GlobalKeyHandlers {
  onEscape?: () => void;
  onCommandPalette?: () => void;
}

/**
 * Global keyboard shortcuts for FlintTrade terminal.
 * Only fires when no input/textarea is focused.
 *
 * Shortcuts:
 *   Ctrl+K  -- Command palette (future)
 *   X       -- Exit all positions (Shift+X = immediate, no confirm)
 *   C       -- Cancel all orders
 *   Esc     -- Close active tool/modal
 *   F1-F8   -- Reserved for widget focus (future)
 */
export default function useGlobalKeys({
  onEscape,
  onCommandPalette,
}: GlobalKeyHandlers): void {
  useEffect(() => {
    function handler(e: KeyboardEvent): void {
      // Skip if user is typing in an input
      const tag = document.activeElement?.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;
      if ((document.activeElement as HTMLElement)?.isContentEditable) return;

      // Ctrl+K -- Command palette
      if ((e.ctrlKey || e.metaKey) && e.key === "k") {
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

      // X -- Exit all positions (with confirmation)
      if (e.key === "x" || e.key === "X") {
        if (e.shiftKey) {
          // Shift+X = immediate exit (no confirm)
          closePosition("Flint").catch(() => {});
          return;
        }
        // Regular X = let the UI handle confirmation
        return;
      }

      // C -- Cancel all orders
      if (e.key === "c" || e.key === "C") {
        if (!e.ctrlKey && !e.metaKey) {
          cancelAllOrders().catch(() => {});
          return;
        }
      }
    }

    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [onEscape, onCommandPalette]);
}
