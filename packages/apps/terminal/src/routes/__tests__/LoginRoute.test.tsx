/**
 * LoginRoute.test.tsx
 *
 * Smoke tests for the login form component.
 * Mocks authStore and brand logo to keep tests lightweight.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

const { mockSetLoggedIn, mockSetMode, modeState } = vi.hoisted(() => ({
  mockSetLoggedIn: vi.fn(),
  mockSetMode: vi.fn((mode: "explore" | "practice" | "live") => {
    modeState.mode = mode;
  }),
  modeState: { mode: "explore" as "explore" | "practice" | "live" },
}));

vi.mock("@/stores/authStore", () => ({
  useAuthStore: Object.assign(() => ({}), {
    getState: () => ({
      setLoggedIn: mockSetLoggedIn,
      setLoggedOut: vi.fn(),
      username: "testuser",
    }),
    setState: vi.fn(),
  }),
}));

vi.mock("@/stores/modeStore", () => ({
  useModeStore: Object.assign(() => ({}), {
    getState: () => ({
      mode: modeState.mode,
      setMode: mockSetMode,
    }),
    setState: vi.fn(),
  }),
}));

vi.mock("@/components/brand/Logo", () => ({
  LogoIcon: ({ size }: { size: number }) => (
    <svg data-testid="logo-icon" width={size} height={size} />
  ),
}));

// ---------------------------------------------------------------------------
// Import after mocks
// ---------------------------------------------------------------------------

import LoginRoute from "../LoginRoute";

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("LoginRoute", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.clearAllMocks();
    modeState.mode = "explore";
  });

  it("renders the login form with heading", () => {
    render(<LoginRoute onSuccess={vi.fn()} mode="full" />);

    expect(screen.getByText("Welcome Back")).toBeInTheDocument();
  });

  it("has password and 2FA code inputs in full mode", () => {
    render(<LoginRoute onSuccess={vi.fn()} mode="full" />);

    expect(screen.getByLabelText("Enter your password")).toBeInTheDocument();
    expect(screen.getByLabelText("Enter your 2FA code")).toBeInTheDocument();
  });

  it("has a Sign In button in full mode", () => {
    render(<LoginRoute onSuccess={vi.fn()} mode="full" />);

    expect(screen.getByRole("button", { name: /sign in/i })).toBeInTheDocument();
  });

  it("clears a stale Live UI mode after normal password and 2FA login", async () => {
    modeState.mode = "live";
    const onSuccess = vi.fn();
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          status: "success",
          data: { token: "explore-session", username: "testuser", expires_at: "2026-07-02T08:00:00+05:30" },
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );
    render(<LoginRoute onSuccess={onSuccess} mode="full" />);

    fireEvent.change(screen.getByLabelText("Enter your password"), { target: { value: "password" } });
    fireEvent.change(screen.getByLabelText("Enter your 2FA code"), { target: { value: "123456" } });
    fireEvent.click(screen.getByRole("button", { name: /sign in/i }));

    await waitFor(() => expect(onSuccess).toHaveBeenCalledOnce());
    expect(mockSetLoggedIn).toHaveBeenCalledWith("explore-session", "testuser", "2026-07-02T08:00:00+05:30");
    expect(mockSetMode).toHaveBeenCalledWith("explore");
  });
});
