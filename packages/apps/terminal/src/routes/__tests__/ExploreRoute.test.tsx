/**
 * ExploreRoute.test.tsx
 *
 * Smoke tests for the /explore demo preview page.
 * Mocks framer-motion, stores, Magic UI, Aceternity UI, and DemoChoice.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";
import { MemoryRouter } from "react-router-dom";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

const { mockNavigate, mockSetMode, mockSetLoggedIn } = vi.hoisted(() => ({
  mockNavigate: vi.fn(),
  mockSetMode: vi.fn(),
  mockSetLoggedIn: vi.fn(),
}));

vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual<typeof import("react-router-dom")>("react-router-dom");
  return {
    ...actual,
    useNavigate: () => mockNavigate,
  };
});

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
      getActiveTheme: () => ({
        shared: {
          particles: {
            quantity: 35,
            sizeRange: [1, 3],
            behavior: "drift",
          },
        },
      }),
    }),
  ),
}));

vi.mock("@/stores/modeStore", () => ({
  useModeStore: Object.assign(() => ({}), {
    getState: () => ({ setMode: mockSetMode }),
  }),
}));

vi.mock("@/stores/authStore", () => ({
  useAuthStore: Object.assign(() => ({}), {
    getState: () => ({ setLoggedIn: mockSetLoggedIn }),
  }),
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

vi.mock("@/components/demo/DemoChoice", () => ({
  default: () => null,
  hasMadeDemoChoice: () => false,
  resetDemoChoice: vi.fn(),
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
    localStorage.clear();
  });

  it("renders the explore page immediately without the demo choice interstitial", () => {
    renderExplore();

    expect(screen.getByRole("main", { name: /explore mode/i })).toBeInTheDocument();
    expect(screen.getByText("Explore FlintTrade")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /demo mode/i })).toBeInTheDocument();
    expect(screen.queryByText(/how would you like to explore flinttrade/i)).not.toBeInTheDocument();
  });

  it("starts the separate demo workspace from the Demo Mode button", () => {
    renderExplore();

    fireEvent.click(screen.getByRole("button", { name: /demo mode/i }));

    expect(mockSetMode).toHaveBeenCalledWith("explore");
    expect(mockSetLoggedIn).toHaveBeenCalledWith("demo-user", "Explorer", "");
    expect(localStorage.getItem("flinttrade:demo-session")).toBe("active");
    expect(mockNavigate).toHaveBeenCalledWith("/home");
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
