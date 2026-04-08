/**
 * useAuthGuard.test.ts
 *
 * Tests for the auth guard hook — verifies redirect behaviour
 * and authenticated access.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

const mockNavigate = vi.fn();

vi.mock("react-router-dom", () => ({
  useNavigate: () => mockNavigate,
}));

// We mock the store module so we can control status externally.
// The real store is Zustand — we replicate the selector pattern.
let mockStatus: string = "unknown";
const mockSetLoggedIn = vi.fn();
const mockSetLoggedOut = vi.fn();
const mockSetSetupRequired = vi.fn();

vi.mock("@/stores/authStore", () => ({
  useAuthStore: (selector: (state: Record<string, unknown>) => unknown) =>
    selector({ status: mockStatus }),
}));

// We also need to stub the static getState() used inside the hook
// for the fetch-based status check. We do that by patching the module.
// Because the hook accesses useAuthStore.getState(), we must attach it.
import { useAuthStore } from "@/stores/authStore";

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
    mockStatus = "unknown";
    mockNavigate.mockReset();
    mockSetLoggedIn.mockReset();
    mockSetLoggedOut.mockReset();
    mockSetSetupRequired.mockReset();

    // Attach getState to the mocked useAuthStore
    (useAuthStore as unknown as Record<string, unknown>).getState = () => ({
      status: mockStatus,
      setLoggedIn: mockSetLoggedIn,
      setLoggedOut: mockSetLoggedOut,
      setSetupRequired: mockSetSetupRequired,
    });
  });

  it("redirects to /welcome when status is logged-out", () => {
    mockStatus = "logged-out";
    renderHook(() => useAuthGuard());

    expect(mockNavigate).toHaveBeenCalledWith("/welcome", { replace: true });
  });

  it("redirects to /welcome when status is setup-required", () => {
    mockStatus = "setup-required";
    renderHook(() => useAuthGuard());

    expect(mockNavigate).toHaveBeenCalledWith("/welcome", { replace: true });
  });

  it("allows access when status is logged-in", () => {
    mockStatus = "logged-in";
    const { result } = renderHook(() => useAuthGuard());

    expect(result.current.isAuthenticated).toBe(true);
    expect(result.current.isLoading).toBe(false);
    expect(mockNavigate).not.toHaveBeenCalled();
  });

  it("returns isLoading true when status is unknown", async () => {
    mockStatus = "unknown";
    // Mock the fetch call that the hook makes when status is unknown
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(JSON.stringify({ data: { is_setup: true } }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );

    const { result } = renderHook(() => useAuthGuard());

    // Initially loading
    expect(result.current.isLoading).toBe(true);

    // After fetch resolves, setLoggedOut is called (is_setup=true means setup done, but no session)
    await waitFor(() => {
      expect(mockSetLoggedOut).toHaveBeenCalled();
    });
  });
});
