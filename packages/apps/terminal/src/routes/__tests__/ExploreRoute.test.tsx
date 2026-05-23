/**
 * ExploreRoute.test.tsx
 *
 * Smoke tests for the /explore demo preview page.
 * Mocks framer-motion, stores, Magic UI, Aceternity UI, and DemoChoice.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";
import { MemoryRouter } from "react-router-dom";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

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
  },
  AnimatePresence: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

vi.mock("@/lib/motion", () => ({
  motionConfig: {
    prefersReducedMotion: () => true,
    duration: { fast: 0.1, normal: 0.2, slow: 0.3 },
    ease: { enter: [0, 0, 1, 1], exit: [0, 0, 1, 1] },
    variants: {
      slideUp: { initial: {}, animate: {} },
      fadeIn: { initial: {}, animate: {} },
    },
    stagger: () => ({ delay: 0 }),
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

vi.mock("@/components/brand/Logo", () => ({
  LogoIcon: ({ size }: { size: number }) => (
    <svg data-testid="logo-icon" width={size} height={size} />
  ),
}));

vi.mock("@/components/ui/GlassCard", () => ({
  GlassCard: ({ children, ...props }: Record<string, unknown>) => (
    <div {...props}>{children as React.ReactNode}</div>
  ),
}));

vi.mock("@/components/magicui/particles", () => ({
  Particles: () => <div data-testid="particles" />,
}));

vi.mock("@/components/magicui/animated-counter", () => ({
  AnimatedCounter: ({ value, formatter }: { value: number; formatter?: (v: number) => string }) => (
    <span>{formatter ? formatter(value) : value}</span>
  ),
}));

vi.mock("@/components/magicui/shimmer-button", () => ({
  ShimmerButton: ({ children, ...props }: Record<string, unknown>) => (
    <button {...props}>{children as React.ReactNode}</button>
  ),
}));

vi.mock("@/components/aceternity/card-hover-effect", () => ({
  HoverCard: ({ children, ...props }: Record<string, unknown>) => (
    <div {...props}>{children as React.ReactNode}</div>
  ),
}));

// Skip the DemoChoice overlay — pretend user has already made a choice
vi.mock("@/components/demo/DemoChoice", () => ({
  default: () => null,
  hasMadeDemoChoice: () => true,
}));

// ---------------------------------------------------------------------------
// Import after mocks
// ---------------------------------------------------------------------------

import ExploreRoute from "../ExploreRoute";

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

function renderExplore() {
  return render(
    <MemoryRouter initialEntries={["/explore"]}>
      <ExploreRoute />
    </MemoryRouter>,
  );
}

describe("ExploreRoute", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("renders the main landmark and heading", () => {
    renderExplore();

    expect(screen.getByRole("main", { name: /explore mode/i })).toBeInTheDocument();
    expect(screen.getByText("Explore FlintTrade")).toBeInTheDocument();
  });

  it("shows all six module preview cards", () => {
    renderExplore();

    expect(screen.getByLabelText("Explore Trade module")).toBeInTheDocument();
    expect(screen.getByLabelText("Explore Invest module")).toBeInTheDocument();
    expect(screen.getByLabelText("Explore Learn module")).toBeInTheDocument();
    expect(screen.getByLabelText("Explore Strategy Lab module")).toBeInTheDocument();
    expect(screen.getByLabelText("Explore Automate module")).toBeInTheDocument();
    expect(screen.getByLabelText("Explore AI module")).toBeInTheDocument();
  });
});
