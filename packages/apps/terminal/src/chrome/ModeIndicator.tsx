/**
 * ModeIndicator — unified TopBar mode pill + toggle.
 *
 * Replaces both SandboxToggle and ModePill with a single component.
 *
 * Behaviour per mode:
 *   Explore  → Grey "EXPLORE" button. Real users switch to Practice; demo
 *              users are sent to setup so sample mode does not hit live APIs.
 *   Practice → Amber "PRACTICE" button. Clicking toggles to Live (requires PIN).
 *   Live     → Green "LIVE" button. Clicking toggles to Practice (instant, no dialog).
 *
 * Visual design follows Thinkorswim-style prominence:
 *   - The dangerous mode (Live) is visually loud
 *   - The safe mode (Practice) is visually distinct but calmer
 *   - Explore is the most subdued
 */

import { useState, useCallback } from "react";
import { Compass, FlaskConical, Zap } from "lucide-react";
import { Input } from "@/components/ui/input";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { useModeStore } from "@/stores/modeStore";
import { useAuthStore } from "@/stores/authStore";
import { downgradeMode, unlockWithPin } from "@/lib/modeAuth";

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function ModeIndicator() {
  const mode = useModeStore((s) => s.mode);
  const setMode = useModeStore((s) => s.setMode);
  const token = useAuthStore((s) => s.token);
  const updateToken = useAuthStore((s) => s.updateToken);

  const [confirmOpen, setConfirmOpen] = useState(false);
  const [pin, setPin] = useState("");
  const [pinError, setPinError] = useState("");
  const [toggleError, setToggleError] = useState("");

  const handleToggle = useCallback(async () => {
    if (mode === "live") {
      // Live → Practice: must revoke the live-unlocked JWT on the server
      // and replace it with a fresh Practice JWT. Without this the
      // backend's require_live_unlocked guard would still let the stale
      // token place real orders even though the UI says Practice.
      setToggleError("");
      try {
        const authState = useAuthStore.getState();
        const newToken = await downgradeMode("practice", authState.token);
        if (!updateToken(newToken, authState.sessionGeneration)) return;
      } catch {
        setToggleError("Could not downgrade to Practice — try again.");
        return;
      }
      setMode("practice");
    } else {
      // Practice → Live: requires PIN confirmation
      setPin("");
      setPinError("");
      setConfirmOpen(true);
    }
    // `token` is deliberately not a dependency: the live→practice branch reads
    // the freshest token from `useAuthStore.getState()` rather than the closure,
    // so listing it here only churned this callback's identity on every refresh.
  }, [mode, setMode, updateToken]);

  const handleConfirmLive = useCallback(async () => {
    if (pin.length !== 6 || /\D/.test(pin)) {
      setPinError("Enter your 6-digit PIN.");
      return;
    }
    try {
      const expectedGeneration = useAuthStore.getState().sessionGeneration;
      // Explicit Live arm: unlockWithPin defaults to mode "live", so the
      // backend mints a live_mode_unlocked JWT. Capturing it is essential —
      // otherwise the in-memory token stays at the Explore/Practice JWT from
      // login and the server-side require_live_unlocked guard rejects every
      // order. (Fixed 2026-05-19 per Codex audit; centralised in Phase 1.)
      const { token: newToken } = await unlockWithPin(pin, "live");
      if (!updateToken(newToken, expectedGeneration)) return;
    } catch (err) {
      // Surface the server's message — the backend distinguishes a wrong PIN
      // from no-PIN-set (code `pin_not_set` points the operator at Settings →
      // Security to create one). The hardcoded string is a last-resort
      // fallback only.
      const message = err instanceof Error ? err.message.trim() : "";
      setPinError(message || "Incorrect PIN. Try again.");
      return;
    }
    setPinError("");
    setConfirmOpen(false);
    setMode("live");
  }, [pin, setMode, updateToken]);

  const handleCancel = useCallback(() => {
    setConfirmOpen(false);
    setPin("");
    setPinError("");
  }, []);

  const handleExploreClick = useCallback(async () => {
    if (token === "demo-user") {
      window.dispatchEvent(
        new CustomEvent("flinttrade:navigate", { detail: { path: "/setup" } }),
      );
      return;
    }
    // Explore → Practice must upgrade the JWT server-side. Login always mints
    // an `explore` JWT, so without this call the UI would show Practice while
    // the backend still saw Explore and rejected every sandbox order 403
    // `mode_blocked` — the Phase 1 G1 bug that made Practice trading
    // unreachable. `/auth/mode` accepts the practice downgrade from an explore
    // token (explore is the lowest mode; practice is a broker-free sandbox).
    setToggleError("");
    try {
      const authState = useAuthStore.getState();
      const newToken = await downgradeMode("practice", authState.token);
      if (!updateToken(newToken, authState.sessionGeneration)) return;
    } catch {
      setToggleError("Could not switch to Practice — try again.");
      return;
    }
    setMode("practice");
  }, [setMode, token, updateToken]);

  // ── Explore → Practice ──────────────────────────────────────────────────
  if (mode === "explore") {
    return (
      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={handleExploreClick}
          aria-label={
            token === "demo-user"
              ? "Explore mode active — sample data only. Click to set up Practice mode."
              : "Explore mode active — sample data only. Click to switch to Practice mode."
          }
          className="flex items-center gap-1 h-7 px-2.5 rounded text-xs font-medium font-heading bg-text-muted/15 text-text-secondary border border-text-muted/20 hover:bg-text-muted/25 hover:text-text-primary transition-colors"
        >
          <Compass size={11} aria-hidden="true" />
          EXPLORE
        </button>
        {toggleError && (
          <span role="alert" className="text-xs text-loss">
            {toggleError}
          </span>
        )}
      </div>
    );
  }

  // ── Practice ↔ Live toggle ──────────────────────────────────────────────

  if (mode === "practice") {
    return (
      <>
        <button
          onClick={handleToggle}
          aria-label="Practice mode active — virtual capital. Click to switch to Live trading."
          className="flex items-center gap-1 h-7 px-2.5 rounded text-xs font-medium font-heading bg-amber-500/15 text-amber-400 border border-amber-500/30 hover:bg-amber-500/25 transition-colors"
        >
          <FlaskConical size={11} aria-hidden="true" />
          PRACTICE
        </button>

        <AlertDialog open={confirmOpen} onOpenChange={setConfirmOpen}>
          <AlertDialogContent>
            <AlertDialogHeader>
              <AlertDialogTitle>Switch to Live Trading?</AlertDialogTitle>
              <AlertDialogDescription asChild>
                <div className="space-y-3">
                  <p>
                    You are about to switch to <strong>Live mode</strong>. All
                    orders will be executed with <strong>real money</strong>{" "}
                    through your broker.
                  </p>
                  <div>
                    <label
                      htmlFor="mode-pin"
                      className="text-xs font-medium text-text-secondary block mb-1.5"
                    >
                      Enter your PIN to confirm
                    </label>
                    <Input
                      id="mode-pin"
                      type="password"
                      inputMode="numeric"
                      maxLength={6}
                      value={pin}
                      onChange={(e) => {
                        setPin(e.target.value.replace(/\D/g, ""));
                        if (pinError) setPinError("");
                      }}
                      placeholder="6-digit PIN"
                      className="text-center font-mono text-lg tracking-widest max-w-40"
                      onKeyDown={(e) => e.key === "Enter" && handleConfirmLive()}
                      autoFocus
                    />
                    {pinError && (
                      <p className="text-xs text-loss mt-1">{pinError}</p>
                    )}
                  </div>
                </div>
              </AlertDialogDescription>
            </AlertDialogHeader>
            <AlertDialogFooter>
              <AlertDialogCancel onClick={handleCancel}>Cancel</AlertDialogCancel>
              <AlertDialogAction
                onClick={(e) => {
                  // Radix's Action closes the dialog on click by default,
                  // which hid every PIN error. Prevent that so a failed PIN
                  // keeps the dialog open with the server's message visible;
                  // handleConfirmLive closes it explicitly on success.
                  e.preventDefault();
                  void handleConfirmLive();
                }}
                disabled={pin.length !== 6}
                className="bg-profit hover:bg-profit/90 text-white"
              >
                Switch to Live
              </AlertDialogAction>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialog>
      </>
    );
  }

  // mode === "live"
  return (
    <div className="flex items-center gap-2">
      <button
        onClick={handleToggle}
        aria-label="Live trading mode active — real money. Click to switch to Practice mode."
        className="flex items-center gap-1 h-7 px-2.5 rounded text-xs font-medium font-heading bg-profit/20 text-profit border border-profit/40 hover:bg-profit/30 transition-colors"
      >
        <Zap size={11} aria-hidden="true" />
        LIVE
      </button>
      {toggleError && (
        <span
          role="alert"
          className="text-xs text-loss"
        >
          {toggleError}
        </span>
      )}
    </div>
  );
}
