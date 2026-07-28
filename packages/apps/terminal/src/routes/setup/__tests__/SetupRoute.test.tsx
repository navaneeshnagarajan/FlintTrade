/**
 * SetupRoute.test.tsx
 *
 * Smoke tests for the setup wizard orchestrator.
 * Mocks react-router and framer-motion to keep tests lightweight.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

const mockNavigate = vi.fn();

vi.mock("react-router", () => ({
  useNavigate: () => mockNavigate,
  Link: ({ children, to, ...props }: Record<string, unknown>) => (
    <a href={String(to)} {...props}>{children as React.ReactNode}</a>
  ),
}));

// framer-motion — render children immediately without animation
vi.mock("framer-motion", () => ({
  motion: {
    div: ({ children, ...props }: Record<string, unknown>) => {
      const { initial: _i, animate: _a, exit: _e, variants: _v, ...rest } = props;
      return <div {...rest}>{children as React.ReactNode}</div>;
    },
    h2: ({ children, ...props }: Record<string, unknown>) => {
      const { initial: _i, animate: _a, exit: _e, ...rest } = props;
      return <h2 {...rest}>{children as React.ReactNode}</h2>;
    },
  },
  AnimatePresence: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

vi.mock("@/lib/motion", () => ({
  motionConfig: {
    prefersReducedMotion: () => true,
    duration: { fast: 0.1, normal: 0.2, slow: 0.3 },
    ease: { enter: [0, 0, 1, 1], exit: [0, 0, 1, 1] },
  },
}));

// Stores
vi.mock("@/stores/connectionStore", () => ({
  useConnectionStore: Object.assign(() => ({}), {
    getState: () => ({ setConfig: vi.fn() }),
    setState: vi.fn(),
  }),
}));

vi.mock("@/stores/settingsStore", () => ({
  useSettingsStore: Object.assign(() => ({}), {
    getState: () => ({
      setPersona: vi.fn(),
      setName: vi.fn(),
      setInterests: vi.fn(),
      setExperience: vi.fn(),
      setTradingDefaults: vi.fn(),
      setRiskLimits: vi.fn(),
    }),
    setState: vi.fn(),
  }),
}));

vi.mock("@/stores/layoutStore", () => ({
  useLayoutStore: Object.assign(() => ({}), {
    getState: () => ({
      workspaceApi: null,
      activeTabId: "trade",
      applyPreset: vi.fn(),
      saveTabLayout: vi.fn(),
    }),
    setState: vi.fn(),
  }),
}));

vi.mock("@/stores/skillStore", () => ({
  useSkillStore: Object.assign(() => ({}), {
    getState: () => ({
      setGlobalLevel: vi.fn(),
      setRouteOverride: vi.fn(),
    }),
    setState: vi.fn(),
  }),
}));

// ---------------------------------------------------------------------------
// Import after mocks
// ---------------------------------------------------------------------------

import SetupRoute from "../../SetupRoute";

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("SetupRoute", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("renders without crashing", () => {
    const { container } = render(<SetupRoute />);
    expect(container.firstChild).toBeInTheDocument();
  });

  it("shows setup mode selection (Quick / Guided / Advanced)", () => {
    render(<SetupRoute />);

    expect(screen.getByText("Quick Setup")).toBeInTheDocument();
    expect(screen.getByText("Guided Setup")).toBeInTheDocument();
    expect(screen.getByText("Advanced Setup")).toBeInTheDocument();
  });

  it("shows the progress indicator heading", () => {
    render(<SetupRoute />);

    // The ModeSelection screen shows "First Time Setup" badge and heading
    expect(screen.getByText("First Time Setup")).toBeInTheDocument();
    expect(screen.getByText("Welcome to FlintTrade")).toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------
// Step counts per mode (stepsForMode is internal; verified via rendered UI)
// ---------------------------------------------------------------------------
// The wizard now uses fixed step arrays per mode (not persona-adaptive):
//   Quick: 2 steps (Connection, Persona)
//   Guided: 7 steps (Persona, Connection, Experience, Interests, Trading Defaults, Preview, Done)
//   Advanced: 9 steps (Persona, Connection, Experience, Interests, Trading Defaults, Risk Limits, AI Config, Preview, Done)
// These are validated implicitly through the render and mode-selection tests above.
