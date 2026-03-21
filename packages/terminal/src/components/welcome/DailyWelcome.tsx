import { useEffect, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { X, AlertTriangle } from "lucide-react";
import { useSettingsStore } from "@/stores/settingsStore";
import { useTradingStore } from "@/stores/tradingStore";
import { useHolidays } from "@/hooks/useMarketStatus";
import type { Holiday } from "@/types/api";
import type { ToolId } from "@/types/widgets";

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

/** Returns today's date in IST as a "YYYY-MM-DD" string for comparison with Holiday.date. */
function getIstDateString(offsetDays = 0): string {
  const now = new Date();
  now.setDate(now.getDate() + offsetDays);
  return now.toLocaleDateString("en-CA", { timeZone: "Asia/Kolkata" }); // "YYYY-MM-DD"
}

/** Formats a "YYYY-MM-DD" date string as "Mon, 26 Jan". */
function formatHolidayDate(dateStr: string): string {
  const [year, month, day] = dateStr.split("-").map(Number);
  const d = new Date(year, month - 1, day);
  return d.toLocaleDateString("en-IN", {
    weekday: "short",
    day: "numeric",
    month: "short",
  });
}

interface HolidayContext {
  /** Non-null when today itself is a holiday for NSE. */
  todayHoliday: Holiday | null;
  /** Non-null when the next calendar day is a holiday for NSE. */
  tomorrowHoliday: Holiday | null;
  /** First holiday within the next 3 days (exclusive of today and tomorrow). */
  upcomingHoliday: Holiday | null;
}

function getHolidayContext(holidays: Holiday[] | undefined): HolidayContext {
  if (!holidays || holidays.length === 0) {
    return { todayHoliday: null, tomorrowHoliday: null, upcomingHoliday: null };
  }

  /** Returns true when NSE is listed as a closed exchange on the holiday. */
  const affectsNse = (h: Holiday): boolean =>
    h.closed_exchanges.some((ex) => ex === "NSE" || ex === "NSE_INDEX");

  const nseHolidays = holidays.filter(affectsNse);

  const today = getIstDateString(0);
  const tomorrow = getIstDateString(1);
  const dayAfter = getIstDateString(2);
  const dayAfterAfter = getIstDateString(3);

  const todayHoliday = nseHolidays.find((h) => h.date === today) ?? null;
  const tomorrowHoliday = nseHolidays.find((h) => h.date === tomorrow) ?? null;
  const upcomingHoliday =
    nseHolidays.find(
      (h) => h.date === dayAfter || h.date === dayAfterAfter,
    ) ?? null;

  return { todayHoliday, tomorrowHoliday, upcomingHoliday };
}

export default function DailyWelcome({ onDismiss }: DailyWelcomeProps) {
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const name = useSettingsStore((s) => s.name);
  const positionCount = useTradingStore((s) => s.positionCount);
  const { data: holidays } = useHolidays();
  const navigate = useNavigate();

  /** Navigate to the lab route (Backtest Lab). */
  function goToLab() {
    onDismiss();
    navigate("/lab");
  }

  /** Navigate to the trade route (Terminal). */
  function goToTrade() {
    onDismiss();
    navigate("/trade");
  }

  /** Navigate to the trade route and open the Trade Journal tool. */
  function openTradeJournal() {
    onDismiss();
    navigate("/trade");
    // Open the trade-journal tool after navigation via the layout store.
    // We schedule a micro-task so the route has time to render.
    setTimeout(() => {
      // The TerminalRoute listens to toolsMenuOpen but tools are opened by
      // setting activeTool inside TerminalRoute. We dispatch a custom event
      // that TerminalRoute can listen to.
      window.dispatchEvent(
        new CustomEvent("flinttrade:open-tool", {
          detail: { toolId: "trade-journal" satisfies ToolId },
        }),
      );
    }, 100);
  }

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
    const { todayHoliday, tomorrowHoliday, upcomingHoliday } =
      getHolidayContext(holidays);

    // Override greeting when today is a holiday
    const baseGreeting = todayHoliday
      ? `Today is ${todayHoliday.description} — markets closed`
      : displayName
        ? `${ctx.greeting}, ${displayName}`
        : ctx.greeting;

    // Override message when tomorrow is a holiday
    const baseMessage = tomorrowHoliday
      ? `Tomorrow: ${tomorrowHoliday.description} — markets closed`
      : ctx.message;

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
          {baseGreeting}
        </p>
        <p className="text-sm text-text-secondary mt-1">{baseMessage}</p>
        {upcomingHoliday && !tomorrowHoliday && (
          <p className="text-xs text-amber-400 mt-2">
            Upcoming: {upcomingHoliday.description} on{" "}
            {formatHolidayDate(upcomingHoliday.date)}
          </p>
        )}
        {ctx.suggestion && !todayHoliday && !tomorrowHoliday && (
          <p
            className="text-xs text-primary mt-2 cursor-pointer hover:underline"
            onClick={
              ctx.suggestion === "Try backtesting a strategy"
                ? goToLab
                : ctx.suggestion === "Open Trade Journal?"
                  ? openTradeJournal
                  : undefined
            }
            role={
              ctx.suggestion === "Try backtesting a strategy" ||
              ctx.suggestion === "Open Trade Journal?"
                ? "button"
                : undefined
            }
          >
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
        <AlertTriangle className="h-5 w-5 text-loss shrink-0" />
        <p className="font-heading font-semibold text-lg text-loss">
          Session recovered
        </p>
      </div>
      <p className="text-sm text-text-secondary mt-1">
        Previous session ended unexpectedly. You have{" "}
        <span className="font-mono text-loss">{positionCount}</span> open
        position{positionCount !== 1 ? "s" : ""}.
      </p>
      <p
        className="text-xs text-loss mt-2 cursor-pointer hover:underline"
        onClick={goToTrade}
        role="button"
      >
        Review positions now
      </p>
    </div>
  );
}
