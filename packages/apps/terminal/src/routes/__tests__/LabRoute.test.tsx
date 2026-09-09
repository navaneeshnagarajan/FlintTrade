/**
 * LabRoute.test.tsx
 *
 * Smoke tests for the /lab Strategy Lab page.
 * Mocks stores, hooks, framer-motion, and API services.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

vi.mock("framer-motion", () => ({
  motion: {
    div: ({ children, ...props }: Record<string, unknown>) => {
      const { initial: _i, animate: _a, exit: _e, variants: _v, transition: _t, layoutId: _l, ...rest } = props;
      return <div {...rest}>{children as React.ReactNode}</div>;
    },
  },
  AnimatePresence: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

vi.mock("@/lib/motion", () => ({
  motionConfig: {
    prefersReducedMotion: () => true,
    duration: { fast: 0.1, normal: 0.2, slow: 0.3 },
    ease: { enter: [0, 0, 1, 1], exit: [0, 0, 1, 1] },
    transitions: { tab: { duration: 0.2 } },
  },
}));

vi.mock("@/hooks/useSkillLevel", () => ({
  useSkillLevel: vi.fn().mockReturnValue("intermediate"),
}));

vi.mock("@/stores/skillStore", () => ({
  useSkillStore: Object.assign(
    vi.fn((selector: (state: Record<string, unknown>) => unknown) =>
      selector({
        globalLevel: "intermediate",
        helpPrefs: { inlineHints: false, spotlightTours: false, aiTutor: false },
      }),
    ),
    {
      getState: () => ({ globalLevel: "intermediate", trackAction: vi.fn() }),
      setState: vi.fn(),
    },
  ),
}));

vi.mock("@/components/help/SpotlightTour", () => ({
  SpotlightTour: () => null,
}));

vi.mock("@/lib/tourDefinitions", () => ({
  TOUR_DEFINITIONS: {},
}));

vi.mock("@/components/motion/TabTransition", () => ({
  default: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

vi.mock("@/components/magicui/animated-counter", () => ({
  AnimatedCounter: ({ value }: { value: number }) => <span>{value}</span>,
}));

vi.mock("@/components/ui/GlassCard", () => ({
  GlassCard: ({ children, ...props }: Record<string, unknown>) => (
    <div {...props}>{children as React.ReactNode}</div>
  ),
}));

vi.mock("@/routes/lab/PineEditor", () => ({
  default: () => <div data-testid="pine-editor" />,
}));

vi.mock("@/services/ftApi", () => ({
  runBacktest: vi.fn(),
  getStrategies: vi.fn().mockResolvedValue([
    {
      name: "sma_crossover",
      description: "Simple moving average crossover starter strategy",
      category: "Trend",
      parameters: [],
    },
  ]),
  getRunningStrategies: vi.fn().mockResolvedValue([]),
  getForwardTrades: vi.fn().mockResolvedValue([]),
  startStrategy: vi.fn(),
  stopStrategy: vi.fn(),
}));

// ---------------------------------------------------------------------------
// Import after mocks
// ---------------------------------------------------------------------------

import LabRoute from "../LabRoute";
import {
  PENDING_TEMPLATE_KEY,
  type BuilderTemplate,
} from "@/tools/StrategyBuilder/templateBridge";

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

function renderLab(path = "/lab") {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <MemoryRouter initialEntries={[path]}>
      <QueryClientProvider client={qc}>
        <LabRoute />
      </QueryClientProvider>
    </MemoryRouter>,
  );
}

describe("LabRoute", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    sessionStorage.clear();
  });

  it("renders the Strategy Lab heading", () => {
    renderLab();

    expect(screen.getByText("Strategy Lab")).toBeInTheDocument();
  });

  it("shows Backtest and Forward Test tabs", () => {
    renderLab();

    expect(screen.getByRole("tab", { name: /backtest/i })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /forward test/i })).toBeInTheDocument();
  });

  it("shows Pine Editor tab", () => {
    renderLab();

    expect(screen.getByRole("tab", { name: /pine editor/i })).toBeInTheDocument();
  });

  it("uses a stable grid layout for backtest config and results", () => {
    renderLab();

    expect(screen.getByTestId("backtest-layout")).toHaveClass("grid");
    expect(screen.getByTestId("backtest-layout").className).toContain("lg:grid-cols");
  });

  it("shows the Options Builder tab", () => {
    renderLab();

    expect(screen.getByRole("tab", { name: /options builder/i })).toBeInTheDocument();
  });

  it("leaves Run Backtest disabled when the Lab opens without a strategy query", async () => {
    renderLab("/lab");

    const run = await screen.findByRole("button", { name: /run backtest/i });
    expect(run).toBeDisabled();
    expect(screen.queryByText("TrendEMACrossover")).not.toBeInTheDocument();
  });

  it("hydrates the Backtest selector from ?strategy= even when the catalogue omits that key", async () => {
    renderLab("/lab?strategy=TrendEMACrossover");

    expect(await screen.findByText("TrendEMACrossover")).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByRole("button", { name: /run backtest/i })).toBeEnabled();
    });
  });

  it("lands on the Options Builder when a template was stashed by the widget", () => {
    const tmpl: BuilderTemplate = {
      id: "straddle",
      name: "Straddle",
      legs: [
        { action: "BUY", optionType: "CE", strikeOffset: 0, lots: 1 },
        { action: "BUY", optionType: "PE", strikeOffset: 0, lots: 1 },
      ],
    };
    sessionStorage.setItem(PENDING_TEMPLATE_KEY, JSON.stringify(tmpl));

    renderLab();

    // The builder tool renders instead of the default Backtest tab…
    expect(screen.getByText("Strategy Builder")).toBeInTheDocument();
    // …with the stashed legs applied (ATM config input + two ATM leg strikes).
    expect(screen.getAllByDisplayValue("22500").length).toBeGreaterThanOrEqual(3);
  });
});
