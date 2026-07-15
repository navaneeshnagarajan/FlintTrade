/**
 * Auth session store — manages JWT token, login state, and idle timeout.
 *
 * Token stored in memory only (never localStorage) for security.
 * Session expires at 08:00 IST daily (enforced via startExpiryTimer).
 */
import { create } from "zustand";
import { clearDemoSession } from "@/lib/demoSession";
import { purgeAuthenticatedQueryCache } from "@/lib/authenticatedQueryCache";
import { useBrokerStore } from "@/stores/brokerStore";
import { useTradingStore } from "@/stores/tradingStore";

type AuthStatus =
  | "unknown"
  | "transitioning"
  | "logged-in"
  | "logged-out"
  | "pin-required"
  | "setup-required";

export interface AuthSessionFence {
  readonly status: AuthStatus;
  readonly principal: string | null;
  readonly generation: number;
}

interface AuthState {
  status: AuthStatus;
  token: string | null;
  /**
   * The still-valid session JWT retained across an idle/manual lock so the
   * PIN unlock can re-authenticate against it (the PIN is a re-auth factor, not
   * a session-minting one — backend policy D6). The ACTIVE `token` is still
   * nulled while locked, so no API call runs during the lock; only the explicit
   * PIN unlock consumes this. Cleared on full login/logout and when the daily
   * 08:00 IST expiry fires — a cold or expired session has none, so a PIN alone
   * can never unlock.
   */
  reauthToken: string | null;
  username: string | null;
  expiresAt: string | null;
  lastActivity: number;
  /** Monotonic fence for async work started under an older auth context. */
  sessionGeneration: number;
  /** Internal: timer ID for the 08:00 IST daily expiry. */
  _expiryTimerId: ReturnType<typeof setTimeout> | null;

  setLoggedIn: (token: string, username: string, expiresAt: string) => void;
  /** Install a login response only if its originating auth context is unchanged. */
  setLoggedInIfCurrent: (
    token: string,
    username: string,
    expiresAt: string,
    expectedFence: AuthSessionFence,
  ) => boolean;
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
  updateToken: (token: string, expectedGeneration: number) => boolean;
}

const IDLE_PIN_THRESHOLD = 5 * 60 * 1000;    // 5 min → PIN required
const IDLE_LOGOUT_THRESHOLD = 30 * 60 * 1000; // 30 min → full logout

function retireAuthenticatedClientState(): void {
  useBrokerStore.getState?.().resetSessionState?.();
  useTradingStore.getState?.().resetSessionState?.();
  purgeAuthenticatedQueryCache();
}

function normalisePrincipal(username: string | null): string | null {
  const principal = username?.trim();
  return principal || null;
}

function authStateMatchesFence(
  state: Pick<AuthState, "status" | "username" | "sessionGeneration">,
  fence: AuthSessionFence,
): boolean {
  return (
    state.status === fence.status &&
    normalisePrincipal(state.username) === fence.principal &&
    state.sessionGeneration === fence.generation
  );
}

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

export const useAuthStore = create<AuthState>((set, get) => {
  const installLoggedInSession = (
    token: string,
    username: string,
    expiresAt: string,
    expectedFence?: AuthSessionFence,
  ): boolean => {
    const current = get();
    if (expectedFence && !authStateMatchesFence(current, expectedFence)) return false;

    const previousPrincipal = normalisePrincipal(current.username);
    const nextGeneration = current.sessionGeneration + 1;
    set({
      status: "transitioning",
      token: null,
      reauthToken: null,
      sessionGeneration: nextGeneration,
    });
    retireAuthenticatedClientState();

    let installed = false;
    set((state) => {
      if (
        state.status !== "transitioning" ||
        state.sessionGeneration !== nextGeneration ||
        normalisePrincipal(state.username) !== previousPrincipal
      ) {
        return state;
      }
      installed = true;
      return {
        status: "logged-in",
        token,
        reauthToken: null,
        username,
        expiresAt,
        lastActivity: Date.now(),
      };
    });
    if (installed) get().startExpiryTimer();
    return installed;
  };

  return {
    status: "unknown",
    token: null,
    reauthToken: null,
    username: null,
    expiresAt: null,
    lastActivity: Date.now(),
    sessionGeneration: 0,
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
      installLoggedInSession(token, username, expiresAt);
    },

    setLoggedInIfCurrent: (token, username, expiresAt, expectedFence) =>
      installLoggedInSession(token, username, expiresAt, expectedFence),

    setLoggedOut: () => {
      // Clear expiry timer on any logout path
      const existing = get()._expiryTimerId;
      if (existing !== null) clearTimeout(existing);
      clearDemoSession();
      set((state) => ({
        status: "logged-out", token: null, reauthToken: null, username: null,
        expiresAt: null, _expiryTimerId: null,
        sessionGeneration: state.sessionGeneration + 1,
      }));
      retireAuthenticatedClientState();
    },

    // Lock the UI but RETAIN the session token for the PIN re-auth (moved out of
    // the active `token` so nothing makes authenticated calls while locked).
    setPinRequired: () => {
      const reauthToken = get().token ?? get().reauthToken;
      set((state) => ({
        status: "pin-required",
        token: null,
        reauthToken,
        sessionGeneration: state.sessionGeneration + 1,
      }));
      retireAuthenticatedClientState();
    },

    setSetupRequired: () => {
      set((state) => ({
        status: "setup-required",
        token: null,
        reauthToken: null,
        username: null,
        sessionGeneration: state.sessionGeneration + 1,
      }));
      retireAuthenticatedClientState();
    },

    updateToken: (token, expectedGeneration) => {
      const current = get();
      const expectedPrincipal = current.username?.trim();
      if (
        current.status !== "logged-in" ||
        !expectedPrincipal ||
        current.sessionGeneration !== expectedGeneration
      ) {
        return false;
      }

      const nextGeneration = expectedGeneration + 1;
      set({
        status: "transitioning",
        token: null,
        sessionGeneration: nextGeneration,
      });
      retireAuthenticatedClientState();

      let updated = false;
      set((state) => {
        if (
          state.status !== "transitioning" ||
          state.sessionGeneration !== nextGeneration ||
          state.username?.trim() !== expectedPrincipal
        ) {
          return state;
        }
        updated = true;
        return {
          status: "logged-in",
          token,
          reauthToken: null,
          lastActivity: Date.now(),
        };
      });
      return updated;
    },

    touchActivity: () => set({ lastActivity: Date.now() }),

    checkIdle: () => {
      const { status, lastActivity } = get();
      if (status !== "logged-in") return;

      const idle = Date.now() - lastActivity;
      if (idle >= IDLE_LOGOUT_THRESHOLD) {
        get().setLoggedOut();
      } else if (idle >= IDLE_PIN_THRESHOLD) {
        get().setPinRequired();
      }
    },
  };
});

/** Capture the complete auth context for asynchronous work. */
export function captureAuthSessionFence(): AuthSessionFence {
  const state = useAuthStore.getState();
  return {
    status: state.status,
    principal: normalisePrincipal(state.username),
    generation: state.sessionGeneration,
  };
}

/** Return whether asynchronous work still belongs to its originating auth context. */
export function isAuthSessionFenceCurrent(fence: AuthSessionFence): boolean {
  return authStateMatchesFence(useAuthStore.getState(), fence);
}
