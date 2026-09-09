/**
 * FT-DEMO-001 — Investor Dashboard header holdings badge.
 *
 * The sample `/demo-app/invest` header must count the Explore demo book,
 * not the empty live query that Explore disables.
 */

import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router";
import { getDemoHoldings } from "@/hooks/useModeData";
import { useModeStore } from "@/stores/modeStore";

vi.mock("framer-motion", () => ({
  motion: {
    div: ({ children, ...props }: Record<string, unknown>) => (
      <div {...props}>{children as React.ReactNode}</div>
    ),
  },
}));

vi.mock("@/lib/motion", () => ({
  motionConfig: {
    prefersReducedMotion: () => true,
    transitions: { tab: { duration: 0 } },
  },
}));

vi.mock("@/hooks/useSkillLevel", () => ({
  useSkillLevel: () => "advanced",
}));

vi.mock("@/stores/skillStore", () => ({
  useSkillStore: Object.assign(() => ({}), {
    getState: () => ({ trackAction: vi.fn() }),
  }),
}));

vi.mock("@/components/help/SpotlightTour", () => ({
  SpotlightTour: () => null,
}));

vi.mock("@/lib/tourDefinitions", () => ({
  TOUR_DEFINITIONS: {},
}));

vi.mock("@/hooks/useHoldings", () => ({
  useHoldings: () => ({
    data: undefined,
    isLoading: false,
    isError: false,
    refetch: vi.fn(),
  }),
}));

vi.mock("@/hooks/useFunds", () => ({
  useFunds: () => ({ data: undefined, isLoading: false }),
}));

vi.mock("@/hooks/useAccountReadsEnabled", () => ({
  useAccountReadsEnabled: () => false,
}));

import InvestRoute from "../InvestRoute";

function renderInvest() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <InvestRoute />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

afterEach(() => {
  useModeStore.setState({ mode: "explore" });
});

describe("InvestRoute header holdings badge (FT-DEMO-001)", () => {
  it("shows the demo holdings count in explore mode", () => {
    useModeStore.setState({ mode: "explore" });
    renderInvest();

    expect(screen.getByText(`${getDemoHoldings().length} holdings`)).toBeInTheDocument();
  });

  it("shows 0 holdings in live mode when the broker book is empty", () => {
    useModeStore.setState({ mode: "live" });
    renderInvest();

    expect(screen.getByText("0 holdings")).toBeInTheDocument();
  });
});
