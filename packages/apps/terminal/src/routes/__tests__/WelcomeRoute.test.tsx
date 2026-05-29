/**
 * WelcomeRoute.test.tsx
 *
 * Smoke tests for the cinematic welcome screen.
 * Mocks framer-motion, stores, Magic UI, and Aceternity UI.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

const { mockNavigate, mockSetMode, mockSetLoggedIn } = vi.hoisted(() => ({
  mockNavigate: vi.fn(),
  mockSetMode: vi.fn(),
  mockSetLoggedIn: vi.fn(),
}));

vi.mock("react-router-dom", () => ({
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

vi.mock("@/stores/themeStore", () => ({
  useThemeStore: vi.fn((selector: (state: Record<string, unknown>) => unknown) =>
    selector({
      activeThemeId: "default",
      mode: "dark",
      setMode: vi.fn(),
    }),
  ),
}));

vi.mock("@/stores/authStore", () => ({
  useAuthStore: Object.assign(
    vi.fn((selector: (state: Record<string, unknown>) => unknown) =>
      selector({ status: "setup-required" }),
    ),
    {
      getState: () => ({
        status: "setup-required",
        setSetupRequired: vi.fn(),
        setLoggedOut: vi.fn(),
        setLoggedIn: mockSetLoggedIn,
      }),
      setState: vi.fn(),
    },
  ),
}));

vi.mock("@/stores/modeStore", () => ({
  useModeStore: Object.assign(() => ({}), {
    getState: () => ({ setMode: mockSetMode }),
    setState: vi.fn(),
  }),
}));

vi.mock("@/components/brand/Logo", () => ({
  LogoIcon: ({ size }: { size: number }) => (
    <svg data-testid="logo-icon" width={size} height={size} />
  ),
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

vi.mock("@/routes/LoginRoute", () => ({
  default: () => <div data-testid="login-route" />,
}));

// ---------------------------------------------------------------------------
// Import after mocks
// ---------------------------------------------------------------------------

import WelcomeRoute from "../WelcomeRoute";

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("WelcomeRoute", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders the welcome heading", () => {
    render(<WelcomeRoute />);

    expect(screen.getByRole("heading", { name: "FlintTrade" })).toBeInTheDocument();
  });

  it("shows Get Started and Explore CTAs for setup-required users", () => {
    render(<WelcomeRoute />);

    expect(screen.getByText("Get Started")).toBeInTheDocument();
    expect(screen.getByLabelText("Explore FlintTrade without creating an account")).toBeInTheDocument();
  });

  it("opens the separate Explore page without entering demo mode", () => {
    render(<WelcomeRoute />);

    fireEvent.click(screen.getByLabelText("Explore FlintTrade without creating an account"));

    expect(mockNavigate).toHaveBeenCalledWith("/explore");
    expect(mockSetMode).not.toHaveBeenCalled();
    expect(mockSetLoggedIn).not.toHaveBeenCalled();
  });
});
