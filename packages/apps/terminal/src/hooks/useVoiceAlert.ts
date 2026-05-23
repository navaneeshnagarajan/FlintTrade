/**
 * useVoiceAlert — Web Speech API synthesis hook for trading alerts.
 *
 * Wraps `window.speechSynthesis` with a clean React interface.  Falls back
 * gracefully when the browser does not support speech synthesis (no-op
 * functions, `isSupported: false`).
 *
 * Respects the `voice_alerts` preference in `settingsStore`.  When the user
 * has turned off voice alerts, all functions are silent no-ops even if
 * `speechSynthesis` is available.
 *
 * Usage:
 *   const { speak, announceOrder, announceAlert } = useVoiceAlert();
 *   announceOrder("BUY", "NIFTY", 50);   // "Buy 50 NIFTY"
 *   announceAlert("NIFTY has crossed above 22000");
 */

import { useCallback, useRef } from "react";
import { useSettingsStore } from "@/stores/settingsStore";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface SpeakOptions {
  /** Speech rate (0.1–10, default 1.0). */
  rate?: number;
  /** Pitch (0–2, default 1.0). */
  pitch?: number;
  /** Volume (0–1, default 1.0). */
  volume?: number;
}

export interface UseVoiceAlertReturn {
  /** True when `window.speechSynthesis` is available in this browser. */
  isSupported: boolean;
  /**
   * Speak arbitrary text aloud.
   *
   * @param text     - The text to synthesise.
   * @param options  - Optional rate, pitch, and volume overrides.
   */
  speak: (text: string, options?: SpeakOptions) => void;
  /**
   * Announce a completed order placement in a consistent format.
   *
   * @param action  - "BUY" or "SELL".
   * @param symbol  - Instrument symbol (e.g. "NIFTY", "BANKNIFTY24OCT").
   * @param qty     - Number of units filled.
   */
  announceOrder: (action: "BUY" | "SELL", symbol: string, qty: number) => void;
  /**
   * Announce a price alert or system notification.
   *
   * @param message - The alert text to read aloud.
   */
  announceAlert: (message: string) => void;
}

// ---------------------------------------------------------------------------
// Internal helpers
// ---------------------------------------------------------------------------

/** Return true if the Web Speech synthesis API is available right now. */
function _checkSupported(): boolean {
  return typeof window !== "undefined" && "speechSynthesis" in window;
}

/** Build and dispatch a SpeechSynthesisUtterance with given options. */
function _utter(text: string, options: SpeakOptions = {}): void {
  if (!_checkSupported() || !text.trim()) return;

  // Cancel any ongoing utterance so we don't queue up stale announcements.
  window.speechSynthesis.cancel();

  const utterance = new SpeechSynthesisUtterance(text);
  utterance.rate   = options.rate   ?? 1.0;
  utterance.pitch  = options.pitch  ?? 1.0;
  utterance.volume = options.volume ?? 1.0;
  utterance.lang   = "en-IN";

  window.speechSynthesis.speak(utterance);
}

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

/**
 * React hook for voice alerts via the Web Speech API (synthesis).
 *
 * All returned functions are stable (wrapped in `useCallback` with no
 * changing dependencies) and are safe to use inside `useEffect` or as
 * event handlers.
 *
 * @returns `{ isSupported, speak, announceOrder, announceAlert }`.
 *
 * @example
 * ```tsx
 * const { announceOrder } = useVoiceAlert();
 * // After successful order placement:
 * announceOrder("BUY", "NIFTY", 50);
 * ```
 */
export function useVoiceAlert(): UseVoiceAlertReturn {
  // Evaluate at call-time so tests can mock window.speechSynthesis before
  // the first render without needing module-level re-evaluation.
  const isSupported = _checkSupported();

  // Read voice_alerts preference from settingsStore.
  // We access it via a ref so callbacks never need to be recreated when
  // the preference changes — the ref is kept up-to-date on every render.
  const voiceAlertsEnabled = useSettingsStore(
    (s) => (s as { voice_alerts?: boolean }).voice_alerts ?? false,
  );
  const enabledRef = useRef(voiceAlertsEnabled);
  enabledRef.current = voiceAlertsEnabled;

  const speak = useCallback((text: string, options?: SpeakOptions): void => {
    if (!_checkSupported() || !enabledRef.current) return;
    _utter(text, options);
  }, []);

  const announceOrder = useCallback(
    (action: "BUY" | "SELL", symbol: string, qty: number): void => {
      if (!_checkSupported() || !enabledRef.current) return;
      // e.g. "Buy 50 NIFTY"
      const verb = action === "BUY" ? "Buy" : "Sell";
      // Pronounce concatenated option symbols more naturally by inserting
      // spaces between segments if no spaces already exist.
      const pronounceable = symbol.replace(/([A-Z])(\d)/, "$1 $2")
                                  .replace(/(\d)([A-Z])/, "$1 $2");
      _utter(`${verb} ${qty} ${pronounceable}`);
    },
    [],
  );

  const announceAlert = useCallback((message: string): void => {
    if (!_checkSupported() || !enabledRef.current) return;
    _utter(message);
  }, []);

  if (!isSupported) {
    return {
      isSupported: false,
      speak: () => undefined,
      announceOrder: () => undefined,
      announceAlert: () => undefined,
    };
  }

  return {
    isSupported,
    speak,
    announceOrder,
    announceAlert,
  };
}
