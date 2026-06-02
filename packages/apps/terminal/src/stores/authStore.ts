/**
 * Auth session store — manages JWT token, login state, and idle timeout.
 *
 * Token stored in memory only (never localStorage) for security.
 * Session expires at 08:00 IST daily (enforced via startExpiryTimer).
 */
import { create } from "zustand";
import { clearDemoSession } from "@/lib/demoSession";

type AuthStatus = "unknown" | "logged-in" | "logged-out" | "pin-required" | "setup-required";

interface AuthState {
  status: AuthStatus;
  token: string | null;
  username: string | null;
  expiresAt: string | null;
  lastActivity: number;
  /** Internal: timer ID for the 08:00 IST daily expiry. */
  _expiryTimerId: ReturnType<typeof setTimeout> | null;

  setLoggedIn: (token: string, username: string, expiresAt: string) => void;
  setLoggedOut: () => void;
  setPinRequired: () => void;
  setSetupRequired: () => void;
  touchActivity: () => void;
  checkIdle: () => void;
  /** Schedules automatic logout at the next 08:00 IST. Called by setLoggedIn. */
  startExpiryTimer: () => void;
  /**
   * Replace the active JWT in-place (used after PIN unlock or
   * mode-switch downgrade). Preserves status/username/expiresAt and
   * resets activity so the idle timer doesn't immediately downgrade.
   */
  updateToken: (token: string) => void;
}

const IDLE_PIN_THRESHOLD = 5 * 60 * 1000;    // 5 min → PIN required
const IDLE_LOGOUT_THRESHOLD = 30 * 60 * 1000; // 30 min → full logout

/**
 * Returns milliseconds until the next 08:00 IST (UTC+05:30 = UTC+02:30).
 * If it is already past 08:00 IST today the timer targets tomorrow's 08:00.
 */
function msUntilNext8amIST(): number {
  const now = new Date();
  const istOffset = 5.5 * 60 * 60 * 1000; // 5h 30m in ms
  const nowIST = new Date(now.getTime() + istOffset);

  // Build the candidate 08:00 IST for today (expressed in UTC: 02:30 UTC)
  const next8am = new Date(nowIST);
  next8am.setUTCHours(2, 30, 0, 0);

  // If we are already at or past 08:00 IST, roll forward one day
  const istHourMinute = nowIST.getUTCHours() * 60 + nowIST.getUTCMinutes();
  if (istHourMinute >= 8 * 60) {
    next8am.setUTCDate(next8am.getUTCDate() + 1);
  }

  return next8am.getTime() - now.getTime();
}

export const useAuthStore = create<AuthState>((set, get) => ({
  status: "unknown",
  token: null,
  username: null,
  expiresAt: null,
  lastActivity: Date.now(),
  _expiryTimerId: null,

  startExpiryTimer: () => {
    // Clear any existing timer before setting a new one
    const existing = get()._expiryTimerId;
    if (existing !== null) clearTimeout(existing);

    const ms = msUntilNext8amIST();
    const timerId = setTimeout(() => {
      get().setLoggedOut();
    }, ms);

    set({ _expiryTimerId: timerId });
  },

  setLoggedIn: (token, username, expiresAt) => {
    set({ status: "logged-in", token, username, expiresAt, lastActivity: Date.now() });
    // Schedule automatic expiry at the next 08:00 IST
    get().startExpiryTimer();
  },

  setLoggedOut: () => {
    // Clear expiry timer on any logout path
    const existing = get()._expiryTimerId;
    if (existing !== null) clearTimeout(existing);
    clearDemoSession();
    set({ status: "logged-out", token: null, username: null, expiresAt: null, _expiryTimerId: null });
  },

  setPinRequired: () =>
    set({ status: "pin-required", token: null }),

  setSetupRequired: () =>
    set({ status: "setup-required", token: null, username: null }),

  updateToken: (token) => set({ token, lastActivity: Date.now() }),

  touchActivity: () => set({ lastActivity: Date.now() }),

  checkIdle: () => {
    const { status, lastActivity } = get();
    if (status !== "logged-in") return;

    const idle = Date.now() - lastActivity;
    if (idle >= IDLE_LOGOUT_THRESHOLD) {
      get().setLoggedOut();
    } else if (idle >= IDLE_PIN_THRESHOLD) {
      set({ status: "pin-required", token: null });
    }
  },
}));
