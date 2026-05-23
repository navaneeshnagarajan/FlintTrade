/**
 * LockScreen — full-screen overlay shown when authStore.status === "pin-required".
 *
 * Displays a subtle animated gradient background, current IST time,
 * and a 6-digit PIN input that auto-submits on completion.
 * A "Use password" link returns to the full login flow.
 */

import { useState, useEffect, useRef, useCallback } from "react";
import { Lock } from "lucide-react";
import { useAuthStore } from "@/stores/authStore";

// ---------------------------------------------------------------------------
// IST clock hook
// ---------------------------------------------------------------------------

function useISTClock(): string {
  const [time, setTime] = useState(() => formatIST());

  useEffect(() => {
    const id = setInterval(() => setTime(formatIST()), 1000);
    return () => clearInterval(id);
  }, []);

  return time;
}

function formatIST(): string {
  return new Intl.DateTimeFormat("en-IN", {
    timeZone: "Asia/Kolkata",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  }).format(new Date());
}

// ---------------------------------------------------------------------------
// PIN dot display
// ---------------------------------------------------------------------------

function PinDots({ filled }: { filled: number }) {
  return (
    <div className="flex items-center gap-3" aria-hidden="true">
      {Array.from({ length: 6 }).map((_, i) => (
        <div
          key={i}
          className={`w-3 h-3 rounded-full transition-all duration-150 ${
            i < filled
              ? "bg-accent scale-110"
              : "bg-border-default"
          }`}
        />
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// LockScreen
// ---------------------------------------------------------------------------

export function LockScreen() {
  const username = useAuthStore((s) => s.username);
  const setLoggedOut = useAuthStore((s) => s.setLoggedOut);
  const setLoggedIn = useAuthStore((s) => s.setLoggedIn);

  const [pin, setPin] = useState("");
  const [error, setError] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const time = useISTClock();

  // Focus the hidden input on mount and whenever lock screen is shown
  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  const submitPin = useCallback(async (value: string) => {
    if (value.length !== 6) return;
    setIsSubmitting(true);
    setError("");
    try {
      const resp = await fetch("/ft-api/v1/auth/pin", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ pin: value }),
      });
      const data = await resp.json();
      if (resp.ok && data.data?.token) {
        setLoggedIn(
          data.data.token,
          data.data.username ?? username ?? "",
          data.data.expires_at ?? "",
        );
      } else {
        setError("Incorrect PIN. Try again.");
        setPin("");
        inputRef.current?.focus();
      }
    } catch {
      setError("Cannot reach server.");
      setPin("");
      inputRef.current?.focus();
    } finally {
      setIsSubmitting(false);
    }
  }, [setLoggedIn, username]);

  function handlePinChange(e: React.ChangeEvent<HTMLInputElement>) {
    const val = e.target.value.replace(/\D/g, "").slice(0, 6);
    setPin(val);
    setError("");
    if (val.length === 6) {
      void submitPin(val);
    }
  }

  function handleUsePassword() {
    // Return to full login — this dismisses the lock screen
    setLoggedOut();
  }

  const displayName = username ?? "User";

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Screen locked"
      className="fixed inset-0 z-50 flex flex-col items-center justify-center backdrop-blur-md"
      style={{ background: "rgba(10,10,15,0.92)" }}
    >
      {/* Subtle animated gradient — screensaver feel */}
      <div
        className="absolute inset-0 pointer-events-none overflow-hidden"
        aria-hidden="true"
      >
        <div
          className="absolute rounded-full opacity-10 blur-3xl"
          style={{
            width: 600,
            height: 600,
            background: "radial-gradient(circle, var(--color-accent, #6366f1) 0%, transparent 70%)",
            top: "30%",
            left: "40%",
            transform: "translate(-50%, -50%)",
            animation: "lockPulse 8s ease-in-out infinite",
          }}
        />
        <div
          className="absolute rounded-full opacity-6 blur-3xl"
          style={{
            width: 400,
            height: 400,
            background: "radial-gradient(circle, #22c55e 0%, transparent 70%)",
            top: "65%",
            left: "60%",
            transform: "translate(-50%, -50%)",
            animation: "lockPulse 12s ease-in-out infinite reverse",
          }}
        />
        <style>{`
          @keyframes lockPulse {
            0%, 100% { opacity: 0.08; transform: translate(-50%, -50%) scale(1); }
            50%       { opacity: 0.14; transform: translate(-50%, -50%) scale(1.12); }
          }
        `}</style>
      </div>

      {/* Content */}
      <div className="relative z-10 flex flex-col items-center gap-8 text-center px-6">

        {/* Time */}
        <p
          className="font-mono font-light text-text-primary select-none"
          style={{ fontSize: "clamp(3rem, 8vw, 5rem)", letterSpacing: "0.05em" }}
          aria-hidden="true"
        >
          {time}
        </p>

        {/* Lock icon + locked label */}
        <div className="flex flex-col items-center gap-2">
          <div className="p-3 rounded-full bg-surface-card border border-border-default">
            <Lock className="size-5 text-text-muted" />
          </div>
          <p className="text-sm text-text-secondary">
            Locked — <span className="text-text-primary font-medium">{displayName}</span>
          </p>
        </div>

        {/* PIN input area */}
        <div className="flex flex-col items-center gap-4">
          <PinDots filled={pin.length} />

          {/* Visually hidden but focusable numeric input */}
          <input
            ref={inputRef}
            type="password"
            inputMode="numeric"
            pattern="[0-9]*"
            maxLength={6}
            value={pin}
            onChange={handlePinChange}
            disabled={isSubmitting}
            aria-label="Enter your 6-digit PIN"
            className="absolute opacity-0 w-px h-px overflow-hidden"
            autoComplete="current-password"
            autoFocus
          />

          {/* Tap to focus hint */}
          <button
            type="button"
            onClick={() => inputRef.current?.focus()}
            className="text-xs text-text-muted hover:text-text-secondary transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent rounded px-2 py-1"
            aria-label="Tap to enter PIN"
          >
            {isSubmitting ? "Verifying…" : "Tap to type PIN"}
          </button>

          {error && (
            <p className="text-xs text-loss" role="alert">
              {error}
            </p>
          )}
        </div>

        {/* Use password link */}
        <button
          type="button"
          onClick={handleUsePassword}
          className="text-xs text-text-muted hover:text-text-primary transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent rounded px-2 py-1 underline underline-offset-2"
        >
          Use password instead
        </button>
      </div>
    </div>
  );
}
