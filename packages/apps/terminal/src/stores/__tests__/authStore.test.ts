/**
 * authStore.test.ts
 *
 * Tests for JWT auth session store — login/logout state, expiry timer,
 * idle timeout, and the safety fix that resets mode on logout.
 */

import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { useAuthStore } from "../authStore";
import { useModeStore } from "../modeStore";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function resetStores() {
  // Clear any pending timers from previous tests
  const timerId = useAuthStore.getState()._expiryTimerId;
  if (timerId !== null) clearTimeout(timerId);

  useAuthStore.setState({
    status: "unknown",
    token: null,
    reauthToken: null,
    username: null,
    expiresAt: null,
    lastActivity: Date.now(),
    _expiryTimerId: null,
  });
  useModeStore.setState({ mode: "explore" });
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("authStore", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    resetStores();
  });

  afterEach(() => {
    // Clean up any lingering timers
    const timerId = useAuthStore.getState()._expiryTimerId;
    if (timerId !== null) clearTimeout(timerId);
    vi.useRealTimers();
  });

  // --- Initial state --------------------------------------------------------

  describe("initial state", () => {
    it("starts with unknown status and no credentials", () => {
      const state = useAuthStore.getState();
      expect(state.status).toBe("unknown");
      expect(state.token).toBeNull();
      expect(state.username).toBeNull();
      expect(state.expiresAt).toBeNull();
      expect(state._expiryTimerId).toBeNull();
    });
  });

  // --- setLoggedIn ----------------------------------------------------------

  describe("setLoggedIn", () => {
    it("sets token, username, status, and expiresAt", () => {
      useAuthStore
        .getState()
        .setLoggedIn("jwt-abc-123", "alice", "2026-04-09T02:30:00Z");

      const state = useAuthStore.getState();
      expect(state.status).toBe("logged-in");
      expect(state.token).toBe("jwt-abc-123");
      expect(state.username).toBe("alice");
      expect(state.expiresAt).toBe("2026-04-09T02:30:00Z");
    });

    it("updates lastActivity on login", () => {
      const before = Date.now();
      useAuthStore
        .getState()
        .setLoggedIn("tok", "user", "2026-04-09T02:30:00Z");
      const after = Date.now();

      const { lastActivity } = useAuthStore.getState();
      expect(lastActivity).toBeGreaterThanOrEqual(before);
      expect(lastActivity).toBeLessThanOrEqual(after);
    });

    it("starts an expiry timer automatically", () => {
      useAuthStore
        .getState()
        .setLoggedIn("tok", "user", "2026-04-09T02:30:00Z");

      expect(useAuthStore.getState()._expiryTimerId).not.toBeNull();
    });
  });

  // --- setLoggedOut ---------------------------------------------------------

  describe("setLoggedOut", () => {
    it("clears all auth state", () => {
      // Log in first
      useAuthStore
        .getState()
        .setLoggedIn("tok", "user", "2026-04-09T02:30:00Z");

      useAuthStore.getState().setLoggedOut();

      const state = useAuthStore.getState();
      expect(state.status).toBe("logged-out");
      expect(state.token).toBeNull();
      expect(state.username).toBeNull();
      expect(state.expiresAt).toBeNull();
      expect(state._expiryTimerId).toBeNull();
    });

    it("does not reset mode on logout (mode is managed separately)", () => {
      // Set mode to live, then log out — mode should remain unchanged
      useModeStore.setState({ mode: "live" });
      expect(useModeStore.getState().mode).toBe("live");

      useAuthStore.getState().setLoggedOut();

      expect(useModeStore.getState().mode).toBe("live");
    });

    it("preserves practice mode on logout", () => {
      useModeStore.setState({ mode: "practice" });
      useAuthStore.getState().setLoggedOut();
      expect(useModeStore.getState().mode).toBe("practice");
    });
  });

  // --- startExpiryTimer -----------------------------------------------------

  describe("startExpiryTimer", () => {
    it("sets a timer ID on the store", () => {
      useAuthStore.getState().startExpiryTimer();
      expect(useAuthStore.getState()._expiryTimerId).not.toBeNull();
    });

    it("triggers setLoggedOut when the timer fires", () => {
      useAuthStore
        .getState()
        .setLoggedIn("tok", "user", "2026-04-09T02:30:00Z");

      expect(useAuthStore.getState().status).toBe("logged-in");

      // Advance past 24 hours (worst case for next 08:00 IST)
      vi.advanceTimersByTime(24 * 60 * 60 * 1000 + 1000);

      expect(useAuthStore.getState().status).toBe("logged-out");
      expect(useAuthStore.getState().token).toBeNull();
    });

    it("clears previous timer when called again", () => {
      useAuthStore.getState().startExpiryTimer();
      const firstTimerId = useAuthStore.getState()._expiryTimerId;

      useAuthStore.getState().startExpiryTimer();
      const secondTimerId = useAuthStore.getState()._expiryTimerId;

      // Timer IDs should differ (previous one was cleared, new one created)
      expect(secondTimerId).not.toBe(firstTimerId);
    });
  });

  // --- Multiple setLoggedIn calls -------------------------------------------

  describe("multiple logins", () => {
    it("clears previous expiry timer on re-login", () => {
      useAuthStore
        .getState()
        .setLoggedIn("tok1", "user1", "2026-04-09T02:30:00Z");
      const firstTimerId = useAuthStore.getState()._expiryTimerId;

      useAuthStore
        .getState()
        .setLoggedIn("tok2", "user2", "2026-04-10T02:30:00Z");
      const secondTimerId = useAuthStore.getState()._expiryTimerId;

      expect(secondTimerId).not.toBe(firstTimerId);
      // Second login's state should be current
      expect(useAuthStore.getState().token).toBe("tok2");
      expect(useAuthStore.getState().username).toBe("user2");
    });
  });

  // --- Idle checking --------------------------------------------------------

  describe("checkIdle", () => {
    it("does nothing when not logged in", () => {
      useAuthStore.setState({ status: "logged-out" });
      useAuthStore.getState().checkIdle();
      expect(useAuthStore.getState().status).toBe("logged-out");
    });

    it("sets pin-required after 5 minutes idle", () => {
      useAuthStore
        .getState()
        .setLoggedIn("tok", "user", "2026-04-09T02:30:00Z");

      // Simulate 6 minutes of idle time
      vi.advanceTimersByTime(6 * 60 * 1000);
      useAuthStore.getState().checkIdle();

      expect(useAuthStore.getState().status).toBe("pin-required");
      expect(useAuthStore.getState().token).toBeNull();
    });

    it("triggers full logout after 30 minutes idle", () => {
      useAuthStore
        .getState()
        .setLoggedIn("tok", "user", "2026-04-09T02:30:00Z");

      // Simulate 31 minutes of idle time
      vi.advanceTimersByTime(31 * 60 * 1000);
      useAuthStore.getState().checkIdle();

      expect(useAuthStore.getState().status).toBe("logged-out");
    });

    it("does not change status when recently active", () => {
      useAuthStore
        .getState()
        .setLoggedIn("tok", "user", "2026-04-09T02:30:00Z");

      // Touch activity, then check immediately
      useAuthStore.getState().touchActivity();
      useAuthStore.getState().checkIdle();

      expect(useAuthStore.getState().status).toBe("logged-in");
    });
  });

  // --- Other actions --------------------------------------------------------

  describe("setPinRequired", () => {
    it("sets status to pin-required and clears token", () => {
      useAuthStore
        .getState()
        .setLoggedIn("tok", "user", "2026-04-09T02:30:00Z");
      useAuthStore.getState().setPinRequired();

      expect(useAuthStore.getState().status).toBe("pin-required");
      expect(useAuthStore.getState().token).toBeNull();
      // username is preserved for re-auth
      expect(useAuthStore.getState().username).toBe("user");
    });
  });

  describe("setSetupRequired", () => {
    it("sets status to setup-required and clears token and username", () => {
      useAuthStore
        .getState()
        .setLoggedIn("tok", "user", "2026-04-09T02:30:00Z");
      useAuthStore.getState().setSetupRequired();

      expect(useAuthStore.getState().status).toBe("setup-required");
      expect(useAuthStore.getState().token).toBeNull();
      expect(useAuthStore.getState().username).toBeNull();
    });
  });

  describe("touchActivity", () => {
    it("updates lastActivity timestamp", () => {
      const before = Date.now();
      useAuthStore.getState().touchActivity();
      const { lastActivity } = useAuthStore.getState();
      expect(lastActivity).toBeGreaterThanOrEqual(before);
    });
  });
});

describe("authStore — session-bound PIN re-auth (D6)", () => {
  it("setPinRequired retains the session token in reauthToken (active token nulled)", () => {
    useAuthStore.getState().setLoggedIn("live-jwt", "nav", "");
    useAuthStore.getState().setPinRequired();
    const s = useAuthStore.getState();
    expect(s.status).toBe("pin-required");
    expect(s.token).toBeNull(); // no authenticated calls while locked
    expect(s.reauthToken).toBe("live-jwt"); // available for the PIN re-auth
  });

  it("idle pin-lock also retains the session token for re-auth", () => {
    useAuthStore.getState().setLoggedIn("live-jwt", "nav", "");
    // Simulate 6 minutes idle (> 5 min PIN threshold, < 30 min logout).
    useAuthStore.setState({ lastActivity: Date.now() - 6 * 60 * 1000 });
    useAuthStore.getState().checkIdle();
    const s = useAuthStore.getState();
    expect(s.status).toBe("pin-required");
    expect(s.token).toBeNull();
    expect(s.reauthToken).toBe("live-jwt");
  });

  it("full logout clears the reauth token so a cold PIN cannot unlock", () => {
    useAuthStore.getState().setLoggedIn("live-jwt", "nav", "");
    useAuthStore.getState().setPinRequired();
    useAuthStore.getState().setLoggedOut();
    expect(useAuthStore.getState().reauthToken).toBeNull();
  });
});
