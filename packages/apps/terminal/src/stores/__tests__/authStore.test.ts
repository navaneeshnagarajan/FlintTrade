/**
 * authStore.test.ts
 *
 * Tests for JWT auth session store — login/logout state, expiry timer,
 * idle timeout, and the safety fix that resets mode on logout.
 */

import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { queryClient } from "@/providers/QueryProvider";
import { captureAuthSessionFence, useAuthStore } from "../authStore";
import { useBrokerStore } from "../brokerStore";
import { useModeStore } from "../modeStore";
import { useTradingStore } from "../tradingStore";

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
    sessionGeneration: 0,
    _expiryTimerId: null,
  });
  useModeStore.setState({ mode: "explore" });
  useBrokerStore.getState().resetSessionState();
  useTradingStore.getState().resetSessionState();
  queryClient.clear();
}

function seedAuthenticatedQueryCache() {
  queryClient.setQueryData(["orders", "alice"], [{ order_id: "order-1" }]);
  queryClient.setQueryData(["portfolio", "alice"], { available_cash: 1000 });
}

function expectAuthenticatedQueryCacheCleared() {
  expect(queryClient.getQueryCache().getAll()).toHaveLength(0);
}

function seedPrincipalMirrors() {
  useBrokerStore.getState().setAccounts([{
    account_id: "alice-account",
    broker: "dhan",
    label: "Alice",
    status: "connected",
    connected_at: null,
    error_message: null,
    is_primary: true,
    source: "native",
  }]);
  useBrokerStore.getState().setActiveAccount("native:dhan:alice-account");
  useTradingStore.getState().updateFromFunds({
    availableCash: 1000,
    usedMargin: 250,
    totalBalance: 1250,
  });
  useTradingStore.getState().setOpenOrderCount(2);
}

function expectPrincipalMirrorsCleared() {
  expect(useBrokerStore.getState().accounts).toEqual([]);
  expect(useBrokerStore.getState().activeAccountId).toBeNull();
  expect(useTradingStore.getState()).toMatchObject({
    totalPnl: 0,
    totalPnlPercent: 0,
    positionCount: 0,
    openOrderCount: 0,
    usedMargin: 0,
    availableMargin: 0,
  });
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

  describe("setLoggedInIfCurrent", () => {
    it("installs an initial login while its originating auth context is current", () => {
      useAuthStore.setState({ status: "logged-out", sessionGeneration: 4 });
      const requestFence = captureAuthSessionFence();

      const installed = useAuthStore.getState().setLoggedInIfCurrent(
        "fresh-token",
        "alice",
        "2026-04-09T02:30:00Z",
        requestFence,
      );

      expect(installed).toBe(true);
      expect(useAuthStore.getState()).toMatchObject({
        status: "logged-in",
        token: "fresh-token",
        username: "alice",
        sessionGeneration: 5,
      });
    });

    it("rejects a login response after another auth transition wins", () => {
      useAuthStore.setState({ status: "logged-out", sessionGeneration: 4 });
      const requestFence = captureAuthSessionFence();
      useAuthStore.getState().setLoggedIn("newer-token", "bob", "");
      const newerSession = useAuthStore.getState();

      const installed = useAuthStore.getState().setLoggedInIfCurrent(
        "late-token",
        "alice",
        "",
        requestFence,
      );

      expect(installed).toBe(false);
      expect(useAuthStore.getState()).toMatchObject({
        status: "logged-in",
        token: newerSession.token,
        username: "bob",
        sessionGeneration: newerSession.sessionGeneration,
      });
    });

    it("rejects a PIN response after the originating principal is logged out", () => {
      useAuthStore.setState({
        status: "pin-required",
        username: "alice",
        reauthToken: "locked-token",
        sessionGeneration: 8,
      });
      const requestFence = captureAuthSessionFence();
      useAuthStore.getState().setLoggedOut();

      const installed = useAuthStore.getState().setLoggedInIfCurrent(
        "late-unlock",
        "alice",
        "",
        requestFence,
      );

      expect(installed).toBe(false);
      expect(useAuthStore.getState()).toMatchObject({
        status: "logged-out",
        token: null,
        username: null,
        sessionGeneration: 9,
      });
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

    it("purges authenticated queries before changing principal", () => {
      useAuthStore.getState().setLoggedIn("tok1", "alice", "");
      seedAuthenticatedQueryCache();

      useAuthStore.getState().setLoggedIn("tok2", "bob", "");

      expectAuthenticatedQueryCacheCleared();
    });

    it("advances the session generation across principal changes", () => {
      useAuthStore.getState().setLoggedIn("tok1", "alice", "");
      const aliceGeneration = useAuthStore.getState().sessionGeneration;

      useAuthStore.getState().setLoggedIn("tok2", "bob", "");

      expect(useAuthStore.getState().sessionGeneration).toBe(aliceGeneration + 1);
    });
  });

  describe("authenticated query cache boundaries", () => {
    it("publishes an inactive PIN state before rotating the query client", () => {
      useAuthStore.getState().setLoggedIn("tok", "alice", "");
      const previousClient = queryClient;
      let clientObservedAtLock: typeof queryClient | null = null;
      const unsubscribe = useAuthStore.subscribe((state) => {
        if (state.status === "pin-required") clientObservedAtLock = queryClient;
      });

      useAuthStore.getState().setPinRequired();
      unsubscribe();

      expect(clientObservedAtLock).toBe(previousClient);
      expect(queryClient).not.toBe(previousClient);
    });

    it("fences principal replacement before publishing the new logged-in state", () => {
      useAuthStore.getState().setLoggedIn("tok1", "alice", "");
      const statuses: string[] = [];
      const clients: Array<typeof queryClient> = [];
      let previousStatus = useAuthStore.getState().status;
      const unsubscribe = useAuthStore.subscribe((state) => {
        if (state.status === previousStatus) return;
        previousStatus = state.status;
        statuses.push(state.status);
        clients.push(queryClient);
      });

      useAuthStore.getState().setLoggedIn("tok2", "bob", "");
      unsubscribe();

      expect(statuses).toEqual(["transitioning", "logged-in"]);
      expect(clients[0]).not.toBe(clients[1]);
      expect(clients[1]).toBe(queryClient);
    });

    it.each([
      ["logout", () => useAuthStore.getState().setLoggedOut()],
      ["PIN lock", () => useAuthStore.getState().setPinRequired()],
      ["setup transition", () => useAuthStore.getState().setSetupRequired()],
    ])("purges every authenticated query on %s", (_transition, applyTransition) => {
      useAuthStore.getState().setLoggedIn("tok", "alice", "");
      seedAuthenticatedQueryCache();

      applyTransition();

      expectAuthenticatedQueryCacheCleared();
    });

    it.each([
      ["logout", () => useAuthStore.getState().setLoggedOut()],
      ["PIN lock", () => useAuthStore.getState().setPinRequired()],
      ["setup transition", () => useAuthStore.getState().setSetupRequired()],
      ["token replacement", () => {
        const expectedGeneration = useAuthStore.getState().sessionGeneration;
        useAuthStore.getState().updateToken("replacement", expectedGeneration);
      }],
      ["principal replacement", () => useAuthStore.getState().setLoggedIn("new", "bob", "")],
    ])("clears principal-derived Zustand mirrors on %s", (_transition, applyTransition) => {
      useAuthStore.getState().setLoggedIn("tok", "alice", "");
      seedPrincipalMirrors();

      applyTransition();

      expectPrincipalMirrorsCleared();
    });

    it("purges every authenticated query when idle checking locks the session", () => {
      useAuthStore.getState().setLoggedIn("tok", "alice", "");
      seedAuthenticatedQueryCache();
      useAuthStore.setState({ lastActivity: Date.now() - 6 * 60 * 1000 });

      useAuthStore.getState().checkIdle();

      expect(useAuthStore.getState().status).toBe("pin-required");
      expectAuthenticatedQueryCacheCleared();
    });

    it("advances the session generation and purges queries when the token changes", () => {
      useAuthStore.getState().setLoggedIn("tok1", "alice", "");
      seedAuthenticatedQueryCache();
      const priorGeneration = useAuthStore.getState().sessionGeneration;

      const updated = useAuthStore.getState().updateToken("tok2", priorGeneration);

      expect(updated).toBe(true);
      expect(useAuthStore.getState().sessionGeneration).toBe(priorGeneration + 1);
      expectAuthenticatedQueryCacheCleared();
    });

    it.each([
      ["logout", () => useAuthStore.getState().setLoggedOut()],
      ["PIN lock", () => useAuthStore.getState().setPinRequired()],
    ])("rejects a token response from before %s", (_transition, applyTransition) => {
      useAuthStore.getState().setLoggedIn("tok1", "alice", "");
      const expectedGeneration = useAuthStore.getState().sessionGeneration;

      applyTransition();
      const stateAfterTransition = useAuthStore.getState();
      const updated = stateAfterTransition.updateToken("late-token", expectedGeneration);

      expect(updated).toBe(false);
      expect(useAuthStore.getState()).toMatchObject({
        status: stateAfterTransition.status,
        token: null,
        username: stateAfterTransition.username,
        sessionGeneration: stateAfterTransition.sessionGeneration,
      });
    });

    it("rejects a token replacement when the active principal is missing", () => {
      useAuthStore.getState().setLoggedIn("tok1", "alice", "");
      const expectedGeneration = useAuthStore.getState().sessionGeneration;
      useAuthStore.setState({ username: null });

      const updated = useAuthStore.getState().updateToken("late-token", expectedGeneration);

      expect(updated).toBe(false);
      expect(useAuthStore.getState()).toMatchObject({
        status: "logged-in",
        token: "tok1",
        username: null,
        sessionGeneration: expectedGeneration,
      });
    });

    it("suppresses an older principal's mutation callback after client retirement", async () => {
      useAuthStore.getState().setLoggedIn("tok1", "alice", "");
      const retiredClient = queryClient;
      let finishMutation: ((value: string) => void) | undefined;
      const mutation = retiredClient.getMutationCache().build<string, Error, void, unknown>(
        retiredClient,
        {
          mutationFn: () => new Promise<string>((resolve) => {
            finishMutation = resolve;
          }),
          onSuccess: (value) => {
            retiredClient.setQueryData(["late-auth-result"], value);
          },
        },
      );
      const completion = mutation.execute(undefined);
      await Promise.resolve();
      expect(finishMutation).toBeTypeOf("function");

      useAuthStore.getState().setLoggedIn("tok2", "bob", "");
      const activeClient = queryClient;
      expect(activeClient).not.toBe(retiredClient);

      finishMutation?.("alice-data");
      await completion;

      expect(retiredClient.getQueryData(["late-auth-result"])).toBeUndefined();
      expect(activeClient.getQueryData(["late-auth-result"])).toBeUndefined();
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
