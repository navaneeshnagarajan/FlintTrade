/**
 * LoginRoute.test.tsx
 *
 * Smoke tests for the login form component.
 * Mocks authStore and brand logo to keep tests lightweight.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

vi.mock("@/stores/authStore", () => ({
  useAuthStore: Object.assign(() => ({}), {
    getState: () => ({
      setLoggedIn: vi.fn(),
      setLoggedOut: vi.fn(),
      username: "testuser",
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
});
