/**
 * useAuthGuard.test.ts
 *
 * Tests for the auth guard hook — verifies redirect behaviour
 * and authenticated access.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { act, renderHook, waitFor } from "@testing-library/react";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

const mockNavigate = vi.fn();

vi.mock("react-router", () => ({
  useNavigate: () => mockNavigate,
}));

const {
  authState,
  captureFence,
  fenceIsCurrent,
  getAuthVersion,
  mockSetLoggedInIfCurrent,
  mockSetLoggedOut,
  mockSetSetupRequired,
  setAuthState,
  subscribeAuth,
} = vi.hoisted(() => {
  const authState = {
    status: "unknown",
    username: null as string | null,
    sessionGeneration: 0,
  };
  const listeners = new Set<() => void>();
  let authVersion = 0;
  const getAuthVersion = () => authVersion;
  const subscribeAuth = (listener: () => void) => {
    listeners.add(listener);
    return () => listeners.delete(listener);
  };
  const setAuthState = (nextState: Partial<typeof authState>) => {
    Object.assign(authState, nextState);
    authVersion += 1;
    listeners.forEach((listener) => listener());
  };
  const captureFence = vi.fn(() => ({
    status: authState.status,
    principal: authState.username?.trim() || null,
    generation: authState.sessionGeneration,
  }));
  const fenceIsCurrent = vi.fn(
    (fence: ReturnType<typeof captureFence>) =>
      fence.status === authState.status &&
      fence.principal === (authState.username?.trim() || null) &&
      fence.generation === authState.sessionGeneration,
  );
  const mockSetLoggedInIfCurrent = vi.fn(
    (
      token: string,
      username: string,
      _expiresAt: string,
      fence: ReturnType<typeof captureFence>,
    ) => {
      if (!fenceIsCurrent(fence)) return false;
      setAuthState({
        status: "logged-in",
        username,
        sessionGeneration: authState.sessionGeneration + 1,
      });
      return Boolean(token);
    },
  );
  const mockSetLoggedOut = vi.fn(() => {
    setAuthState({
      status: "logged-out",
      username: null,
      sessionGeneration: authState.sessionGeneration + 1,
    });
  });
  const mockSetSetupRequired = vi.fn(() => {
    setAuthState({
      status: "setup-required",
      username: null,
      sessionGeneration: authState.sessionGeneration + 1,
    });
  });
  return {
    authState,
    captureFence,
    fenceIsCurrent,
    getAuthVersion,
    mockSetLoggedInIfCurrent,
    mockSetLoggedOut,
    mockSetSetupRequired,
    setAuthState,
    subscribeAuth,
  };
});

vi.mock("@/stores/authStore", async () => {
  const { useSyncExternalStore } =
    await vi.importActual<typeof import("react")>("react");
  return {
    captureAuthSessionFence: captureFence,
    isAuthSessionFenceCurrent: fenceIsCurrent,
    useAuthStore: Object.assign(
      (selector: (state: Record<string, unknown>) => unknown) => {
        useSyncExternalStore(subscribeAuth, getAuthVersion, getAuthVersion);
        return selector(authState);
      },
      {
        getState: () => ({
          ...authState,
          setLoggedInIfCurrent: mockSetLoggedInIfCurrent,
          setLoggedOut: mockSetLoggedOut,
          setSetupRequired: mockSetSetupRequired,
        }),
      },
    ),
  };
});

// ---------------------------------------------------------------------------
// Import after mocks
// ---------------------------------------------------------------------------

import { useAuthGuard } from "../useAuthGuard";

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("useAuthGuard", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    localStorage.clear();
    setAuthState({ status: "unknown", username: null, sessionGeneration: 0 });
    mockNavigate.mockReset();
    vi.clearAllMocks();
  });

  it("redirects to /welcome when status is logged-out", () => {
    authState.status = "logged-out";
    renderHook(() => useAuthGuard());

    expect(mockNavigate).toHaveBeenCalledWith("/welcome", { replace: true });
  });

  it("redirects to /welcome when status is setup-required", () => {
    authState.status = "setup-required";
    renderHook(() => useAuthGuard());

    expect(mockNavigate).toHaveBeenCalledWith("/welcome", { replace: true });
  });

  it("allows access when status is logged-in", () => {
    authState.status = "logged-in";
    authState.username = "alice";
    const { result } = renderHook(() => useAuthGuard());

    expect(result.current.isAuthenticated).toBe(true);
    expect(result.current.isLoading).toBe(false);
    expect(mockNavigate).not.toHaveBeenCalled();
  });

  it("returns isLoading true when status is unknown", async () => {
    authState.status = "unknown";
    // Mock the fetch call that the hook makes when status is unknown
    // AuthStatusSchema (src/lib/schemas/ftApi.ts) requires `status` (string)
    // and `data: { is_setup: boolean, is_locked: boolean }`.
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          status: "success",
          data: { is_setup: true, is_locked: false },
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );

    const { result } = renderHook(() => useAuthGuard());

    // Initially loading
    expect(result.current.isLoading).toBe(true);

    // After fetch resolves, setLoggedOut is called (is_setup=true means setup done, but no session)
    await waitFor(() => {
      expect(mockSetLoggedOut).toHaveBeenCalled();
    });
  });

  it("restores demo workspace auth on reload when explore demo session is active", async () => {
    authState.status = "unknown";
    localStorage.setItem("flinttrade:demo-session", "active");
    localStorage.setItem(
      "flinttrade:mode",
      JSON.stringify({ state: { mode: "explore" }, version: 2 }),
    );
    const fetchSpy = vi.spyOn(globalThis, "fetch");

    const { result } = renderHook(() => useAuthGuard());

    await waitFor(() => {
      expect(mockSetLoggedInIfCurrent).toHaveBeenCalledWith(
        "demo-user",
        "Explorer",
        "",
        { status: "unknown", principal: null, generation: 0 },
      );
    });

    expect(fetchSpy).not.toHaveBeenCalled();
    expect(result.current.isLoading).toBe(false);
    expect(mockNavigate).not.toHaveBeenCalled();
  });

  it("reactively clears loading and ignores a late success after login wins", async () => {
    let finishStatus: ((response: Response) => void) | undefined;
    vi.spyOn(globalThis, "fetch").mockReturnValueOnce(
      new Promise<Response>((resolve) => {
        finishStatus = resolve;
      }),
    );
    const { result } = renderHook(() => useAuthGuard());
    await waitFor(() => expect(globalThis.fetch).toHaveBeenCalledOnce());
    expect(result.current.isLoading).toBe(true);

    act(() => {
      setAuthState({
        status: "logged-in",
        username: "bob",
        sessionGeneration: 1,
      });
    });

    expect(result.current).toEqual({ isAuthenticated: true, isLoading: false });

    await act(async () => {
      finishStatus?.(
        new Response(
          JSON.stringify({
            status: "success",
            data: { is_setup: false, is_locked: false },
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        ),
      );
      await Promise.resolve();
    });

    expect(mockSetSetupRequired).not.toHaveBeenCalled();
    expect(mockSetLoggedOut).not.toHaveBeenCalled();
    expect(authState).toMatchObject({
      status: "logged-in",
      username: "bob",
      sessionGeneration: 1,
    });
    expect(result.current).toEqual({ isAuthenticated: true, isLoading: false });
  });

  it("reactively clears loading and ignores a late failure after login wins", async () => {
    let failStatus: ((error: Error) => void) | undefined;
    vi.spyOn(globalThis, "fetch").mockReturnValueOnce(
      new Promise<Response>((_resolve, reject) => {
        failStatus = reject;
      }),
    );
    const { result } = renderHook(() => useAuthGuard());
    await waitFor(() => expect(globalThis.fetch).toHaveBeenCalledOnce());
    expect(result.current.isLoading).toBe(true);

    act(() => {
      setAuthState({
        status: "logged-in",
        username: "bob",
        sessionGeneration: 1,
      });
    });

    expect(result.current).toEqual({ isAuthenticated: true, isLoading: false });

    await act(async () => {
      failStatus?.(new Error("late failure"));
      await Promise.resolve();
    });

    expect(mockSetLoggedInIfCurrent).not.toHaveBeenCalled();
    expect(mockSetSetupRequired).not.toHaveBeenCalled();
    expect(authState).toMatchObject({
      status: "logged-in",
      username: "bob",
      sessionGeneration: 1,
    });
    expect(result.current).toEqual({ isAuthenticated: true, isLoading: false });
  });
});
