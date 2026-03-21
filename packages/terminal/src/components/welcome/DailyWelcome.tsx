import { useEffect, useRef } from "react";
import { X, AlertTriangle } from "lucide-react";
import { useSettingsStore } from "@/stores/settingsStore";
import { useTradingStore } from "@/stores/tradingStore";

interface DailyWelcomeProps {
  onDismiss: () => void;
}

interface TimeContext {
  greeting: string;
  message: string;
  suggestion?: string;
}

const SESSION_KEY = "flinttrade:sessionActive";

function getTimeContext(): TimeContext | null {
  const now = new Date();
  const ist = new Date(
    now.toLocaleString("en-US", { timeZone: "Asia/Kolkata" }),
  );
  const hour = ist.getHours();
  const mins = hour * 60 + ist.getMinutes();
  const day = ist.getDay();
  const isWeekend = day === 0 || day === 6;

  if (isWeekend) {
    return {
      greeting: "Happy weekend",
      message: "Markets resume Monday 9:15 AM",
      suggestion: "Try backtesting a strategy",
    };
  }

  if (mins < 555) {
    // Before 9:15 AM IST
    const minsToOpen = 555 - mins;
    return {
      greeting: hour < 12 ? "Good morning" : "Hello",
      message: `Market opens in ${Math.floor(minsToOpen / 60)}h ${minsToOpen % 60}m`,
      suggestion: "Review overnight global indices",
    };
  }

  if (mins <= 930) {
    // 9:15 AM - 3:30 PM IST (market hours) -- don't show
    return null;
  }

  if (hour < 20) {
    // Post-market (3:30 PM - 8:00 PM)
    return {
      greeting: "Markets closed",
      message: "Review today's trades",
      suggestion: "Open Trade Journal?",
    };
  }

  return {
    greeting: "Good evening",
    message: "Markets closed for the day",
    suggestion: "Explore learning modules",
  };
}

function detectCrashRecovery(): boolean {
  try {
    return localStorage.getItem(SESSION_KEY) === "true";
  } catch {
    return false;
  }
}

function markSessionActive(): void {
  try {
    localStorage.setItem(SESSION_KEY, "true");
  } catch {
    // Ignore storage errors
  }
}

function handleBeforeUnload(): void {
  try {
    localStorage.setItem(SESSION_KEY, "false");
  } catch {
    // Ignore storage errors
  }
}

export default function DailyWelcome({ onDismiss }: DailyWelcomeProps) {
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const name = useSettingsStore((s) => s.name);
  const positionCount = useTradingStore((s) => s.positionCount);

  const wasCrash = useRef(detectCrashRecovery());

  // Session tracking: mark active on mount, clear on unload
  useEffect(() => {
    markSessionActive();
    window.addEventListener("beforeunload", handleBeforeUnload);
    return () => {
      window.removeEventListener("beforeunload", handleBeforeUnload);
    };
  }, []);

  // Auto-dismiss after 8 seconds
  useEffect(() => {
    timerRef.current = setTimeout(onDismiss, 8000);
    return () => {
      if (timerRef.current) {
        clearTimeout(timerRef.current);
      }
    };
  }, [onDismiss]);

  const isRecovery = wasCrash.current && positionCount > 0;

  // If crash recovery, show the red card regardless of market hours
  if (!isRecovery) {
    const ctx = getTimeContext();
    if (!ctx) {
      // Market hours -- don't render
      onDismiss();
      return null;
    }

    const displayName = name && name !== "Trader" ? name : "";
    const greeting = displayName
      ? `${ctx.greeting}, ${displayName}`
      : ctx.greeting;

    return (
      <div
        className="fixed top-16 right-4 w-80 rounded-lg border border-border-default bg-surface-elevated p-4 shadow-lg z-50 animate-slide-in-right"
        role="status"
        aria-live="polite"
      >
        <button
          onClick={onDismiss}
          className="absolute top-2 right-2 p-1 rounded hover:bg-surface-hover text-text-muted hover:text-text-primary transition-colors"
          aria-label="Dismiss"
        >
          <X className="h-4 w-4" />
        </button>
        <p className="font-heading font-semibold text-lg text-text-primary pr-6">
          {greeting}
        </p>
        <p className="text-sm text-text-secondary mt-1">{ctx.message}</p>
        {ctx.suggestion && (
          <p className="text-xs text-primary mt-2 cursor-pointer hover:underline">
            {ctx.suggestion}
          </p>
        )}
      </div>
    );
  }

  // Recovery card
  return (
    <div
      className="fixed top-16 right-4 w-80 rounded-lg border border-loss bg-[rgba(239,68,68,0.1)] p-4 shadow-lg z-50 animate-slide-in-right"
      role="alert"
      aria-live="assertive"
    >
      <button
        onClick={onDismiss}
        className="absolute top-2 right-2 p-1 rounded hover:bg-surface-hover text-text-muted hover:text-text-primary transition-colors"
        aria-label="Dismiss"
      >
        <X className="h-4 w-4" />
      </button>
      <div className="flex items-center gap-2 pr-6">
        <AlertTriangle className="h-5 w-5 text-loss flex-shrink-0" />
        <p className="font-heading font-semibold text-lg text-loss">
          Session recovered
        </p>
      </div>
      <p className="text-sm text-text-secondary mt-1">
        Previous session ended unexpectedly. You have{" "}
        <span className="font-mono text-loss">{positionCount}</span> open
        position{positionCount !== 1 ? "s" : ""}.
      </p>
      <p className="text-xs text-loss mt-2 cursor-pointer hover:underline">
        Review positions now
      </p>
    </div>
  );
}
