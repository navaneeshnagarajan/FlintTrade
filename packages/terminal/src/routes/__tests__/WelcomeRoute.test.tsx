/**
 * WelcomeRoute.test.tsx
 *
 * Smoke tests for the cinematic welcome screen.
 * Mocks framer-motion, stores, Magic UI, and Aceternity UI.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

const mockNavigate = vi.fn();

vi.mock("react-router-dom", () => ({
  useNavigate: () => mockNavigate,
}));

vi.mock("framer-motion", () => ({
  motion: {
    div: ({ children, ...props }: Record<string, unknown>) => {
      const { initial: _i, animate: _a, exit: _e, variants: _v, transition: _t, whileHover: _w, ...rest } = props;
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
        setLoggedIn: vi.fn(),
      }),
      setState: vi.fn(),
    },
  ),
}));

vi.mock("@/stores/modeStore", () => ({
  useModeStore: Object.assign(() => ({}), {
    getState: () => ({ setMode: vi.fn() }),
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
    vi.restoreAllMocks();
  });

  it("renders the welcome heading", () => {
    render(<WelcomeRoute />);

    // sr-only h1
    expect(screen.getByText("Welcome to FlintTrade")).toBeInTheDocument();
  });

  it("shows Get Started and Explore CTAs for setup-required users", () => {
    render(<WelcomeRoute />);

    expect(screen.getByText("Get Started")).toBeInTheDocument();
    expect(screen.getByLabelText("Explore FlintTrade without creating an account")).toBeInTheDocument();
  });
});
