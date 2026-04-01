/**
 * Auth session store — manages JWT token, login state, and idle timeout.
 *
 * Token stored in memory only (never localStorage) for security.
 * Session expires at 08:00 IST daily.
 */
import { create } from "zustand";

type AuthStatus = "unknown" | "logged-in" | "logged-out" | "pin-required" | "setup-required";

interface AuthState {
  status: AuthStatus;
  token: string | null;
  username: string | null;
  expiresAt: string | null;
  lastActivity: number;

  setLoggedIn: (token: string, username: string, expiresAt: string) => void;
  setLoggedOut: () => void;
  setPinRequired: () => void;
  setSetupRequired: () => void;
  touchActivity: () => void;
  checkIdle: () => void;
}

const IDLE_PIN_THRESHOLD = 5 * 60 * 1000;   // 5 min → PIN required
const IDLE_LOGOUT_THRESHOLD = 30 * 60 * 1000; // 30 min → full logout

export const useAuthStore = create<AuthState>((set, get) => ({
  status: "unknown",
  token: null,
  username: null,
  expiresAt: null,
  lastActivity: Date.now(),

  setLoggedIn: (token, username, expiresAt) =>
    set({ status: "logged-in", token, username, expiresAt, lastActivity: Date.now() }),

  setLoggedOut: () =>
    set({ status: "logged-out", token: null, username: null, expiresAt: null }),

  setPinRequired: () =>
    set({ status: "pin-required", token: null }),

  setSetupRequired: () =>
    set({ status: "setup-required", token: null, username: null }),

  touchActivity: () => set({ lastActivity: Date.now() }),

  checkIdle: () => {
    const { status, lastActivity } = get();
    if (status !== "logged-in") return;

    const idle = Date.now() - lastActivity;
    if (idle >= IDLE_LOGOUT_THRESHOLD) {
      set({ status: "logged-out", token: null });
    } else if (idle >= IDLE_PIN_THRESHOLD) {
      set({ status: "pin-required", token: null });
    }
  },
}));
