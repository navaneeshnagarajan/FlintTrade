/**
 * AIRoute.test.tsx
 *
 * Smoke tests for the /ai AI Center page.
 * Mocks stores, hooks, framer-motion, and API services.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

vi.mock("framer-motion", () => ({
  motion: {
    div: ({ children, ...props }: Record<string, unknown>) => {
      const { initial: _i, animate: _a, exit: _e, variants: _v, transition: _t, layoutId: _l, ...rest } = props;
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
    transitions: { fade: { duration: 0.2 } },
  },
  EASE_ENTER: [0.22, 1, 0.36, 1],
  EASE_EXIT: [0.0, 0.0, 0.58, 1.0],
  EASE_MOVE: [0.0, 0.0, 0.58, 1.0],
  DURATION: { fast: 0.15, normal: 0.3, slow: 0.5 },
}));

vi.mock("@/components/help/SpotlightTour", () => ({
  SpotlightTour: () => null,
}));

vi.mock("@/lib/tourDefinitions", () => ({
  TOUR_DEFINITIONS: {},
}));

vi.mock("@/hooks/useSkillLevel", () => ({
  useSkillLevel: vi.fn().mockReturnValue("intermediate"),
}));

vi.mock("@/stores/skillStore", () => ({
  useSkillStore: Object.assign(
    vi.fn((selector: (state: Record<string, unknown>) => unknown) =>
      selector({ globalLevel: "intermediate" }),
    ),
    {
      getState: () => ({ globalLevel: "intermediate", trackAction: vi.fn() }),
      setState: vi.fn(),
    },
  ),
}));

vi.mock("@/widgets/utility/AIAdvisor/AIAdvisorWidget", () => ({
  default: () => <div data-testid="ai-advisor-widget">AI Advisor</div>,
}));

vi.mock("@/routes/ai/AISuggestionsPanel", () => ({
  default: () => <div data-testid="ai-suggestions-panel" />,
}));

vi.mock("@/services/ftApi", () => ({
  getActiveSignals: vi.fn().mockResolvedValue([]),
  analyzeSentiment: vi.fn(),
  queryKnowledge: vi.fn(),
}));

// ---------------------------------------------------------------------------
// Import after mocks
// ---------------------------------------------------------------------------

import AIRoute from "../AIRoute";

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

function renderAI() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <AIRoute />
    </QueryClientProvider>,
  );
}

describe("AIRoute", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders the AI Center heading", () => {
    renderAI();

    expect(screen.getByText("AI Center")).toBeInTheDocument();
  });

  it("shows navigation with Chat and Signals buttons", () => {
    renderAI();

    const nav = screen.getByRole("navigation", { name: /ai section navigation/i });
    expect(nav).toBeInTheDocument();
    expect(screen.getByLabelText("Chat")).toBeInTheDocument();
    expect(screen.getByLabelText("Signals")).toBeInTheDocument();
  });
});
