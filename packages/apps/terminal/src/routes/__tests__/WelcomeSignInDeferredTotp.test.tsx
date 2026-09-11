/**
 * Tester path for FT-SETUP-002: Set up later → session → Sign Out
 * (no refresh) → daily Sign In must be password-only.
 *
 * LoginRoute is real (not mocked). Welcome's leftover totpRequired prop
 * must not keep the 2FA field after an in-app logout remount.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom";

const { mockNavigate } = vi.hoisted(() => ({
  mockNavigate: vi.fn(),
}));

vi.mock("react-router", () => ({
  useNavigate: () => mockNavigate,
  Link: ({ children, to, ...props }: Record<string, unknown>) => (
    <a href={String(to)} {...props}>{children as React.ReactNode}</a>
  ),
}));

vi.mock("framer-motion", () => ({
  motion: {
    div: ({ children, ...props }: Record<string, unknown>) => {
      const { initial: _i, animate: _a, exit: _e, variants: _v, transition: _t, whileHover: _w, layout: _l, ...rest } = props;
      return <div {...rest}>{children as React.ReactNode}</div>;
    },
    span: ({ children, ...props }: Record<string, unknown>) => {
      const { initial: _i, animate: _a, exit: _e, transition: _t, ...rest } = props;
      return <span {...rest}>{children as React.ReactNode}</span>;
    },
    button: ({ children, ...props }: Record<string, unknown>) => {
      const { initial: _i, animate: _a, exit: _e, transition: _t, ...rest } = props;
      return <button {...rest}>{children as React.ReactNode}</button>;
    },
    p: ({ children, ...props }: Record<string, unknown>) => {
      const { initial: _i, animate: _a, exit: _e, transition: _t, ...rest } = props;
      return <p {...rest}>{children as React.ReactNode}</p>;
    },
  },
  AnimatePresence: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

vi.mock("@/lib/motion", () => ({
  motionConfig: {
    prefersReducedMotion: () => true,
    duration: { fast: 0.1, normal: 0.2, slow: 0.3 },
    ease: { enter: [0, 0, 1, 1], exit: [0, 0, 1, 1] },
    transitions: { fade: { duration: 0.2 } },
  },
}));

vi.mock("@/components/magicui/particles", () => ({
  Particles: () => <div data-testid="particles" />,
}));

vi.mock("@/components/magicui/shimmer-button", () => ({
  ShimmerButton: ({ children, ...props }: Record<string, unknown>) => (
    <button {...props}>{children as React.ReactNode}</button>
  ),
}));

vi.mock("@/components/aceternity/meteors", () => ({
  Meteors: () => <div data-testid="meteors" />,
}));

import WelcomeRoute from "../WelcomeRoute";
import { useAuthStore } from "@/stores/authStore";

describe("Welcome Sign In after Sign Out", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    sessionStorage.setItem("flinttrade:greeted-today", new Date().toDateString());
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
  });

  it("hides 2FA after Set up later session then in-app Sign Out", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url.includes("/v1/auth/status")) {
        return new Response(
          JSON.stringify({
            status: "success",
            data: {
              is_setup: true,
              is_locked: false,
              has_pin: true,
              totp_enabled: false,
            },
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        );
      }
      return new Response(JSON.stringify({ status: "error" }), { status: 500 });
    });

    act(() => {
      useAuthStore.getState().setLoggedIn("explore-session", "nav", "");
      useAuthStore.getState().setLoggedOut();
    });

    render(<WelcomeRoute />);

    await waitFor(() => {
      expect(screen.getByText("Welcome Back")).toBeInTheDocument();
    });
    expect(screen.queryByLabelText("Enter your 2FA code")).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Enter your password"), {
      target: { value: "password" },
    });
    expect(screen.getByRole("button", { name: /sign in/i })).not.toBeDisabled();
  });
});
