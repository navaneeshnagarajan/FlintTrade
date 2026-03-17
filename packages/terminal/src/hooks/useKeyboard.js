import { useEffect } from "react";

/**
 * Global keyboard shortcut handler.
 *
 * @param {function} setModule - function to switch the active module index (0-8)
 * @param {object}   handlers - optional map of extra key handlers:
 *   { onBuy, onSell, onExitAll, onCancelAll, onTrailToggle, onCommandPalette }
 */
export default function useKeyboard(setModule, handlers = {}) {
  useEffect(() => {
    const onKey = (e) => {
      // F1-F8 → module 0-7
      if (e.key >= "F1" && e.key <= "F8") {
        e.preventDefault();
        setModule(parseInt(e.key.slice(1), 10) - 1);
        return;
      }

      // Ctrl+K → command palette
      if ((e.ctrlKey || e.metaKey) && e.key === "k") {
        e.preventDefault();
        handlers.onCommandPalette?.();
        return;
      }

      // Esc → close modal
      if (e.key === "Escape") {
        handlers.onEscape?.();
        return;
      }

      // Skip if user is typing in an input/textarea
      const tag = e.target.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;

      switch (e.key) {
        case "ArrowUp":
          e.preventDefault();
          handlers.onBuy?.();
          break;
        case "ArrowDown":
          e.preventDefault();
          handlers.onSell?.();
          break;
        case "b":
        case "B":
          handlers.onBuy?.();
          break;
        case "s":
        case "S":
          handlers.onSell?.();
          break;
        case "x":
        case "X":
          handlers.onExitAll?.();
          break;
        case "c":
        case "C":
          handlers.onCancelAll?.();
          break;
        case " ":
          e.preventDefault();
          handlers.onTrailToggle?.();
          break;
        case "Enter":
          handlers.onConfirm?.();
          break;
      }
    };

    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [setModule, handlers]);
}
