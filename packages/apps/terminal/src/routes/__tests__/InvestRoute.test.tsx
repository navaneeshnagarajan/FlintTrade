import { describe, it, expect, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";

// Mock framer-motion to avoid animation issues in tests
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

// Mock hooks that depend on stores
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

// Mock the InvestContext provider to supply dummy data
vi.mock("../invest/InvestContext", () => ({
  InvestProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  useInvest: () => ({
    holdings: [],
    summary: {
      currentValue: 0,
      totalInvested: 0,
      totalPnl: 0,
      totalPnlPercent: 0,
      availableCash: 0,
      sectorCount: 0,
      holdingCount: 0,
    },
    isLoading: false,
    isError: false,
    refetchHoldings: vi.fn(),
  }),
}));

import InvestRoute from "../InvestRoute";

function createWrapper() {
  const qc = new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: 0 },
    },
  });
  return function Wrapper({ children }: { children: React.ReactNode }) {
    return (
      <QueryClientProvider client={qc}>
        <MemoryRouter>{children}</MemoryRouter>
      </QueryClientProvider>
    );
  };
}

describe("InvestRoute", () => {
  it("renders the Investor Dashboard heading", () => {
    render(<InvestRoute />, { wrapper: createWrapper() });
    expect(screen.getByText("Investor Dashboard")).toBeInTheDocument();
  });

  it("has tab navigation with multiple tabs", () => {
    render(<InvestRoute />, { wrapper: createWrapper() });
    expect(screen.getByText("Dashboard")).toBeInTheDocument();
    expect(screen.getByText("Holdings")).toBeInTheDocument();
    expect(screen.getByText("SIPs")).toBeInTheDocument();
    expect(screen.getByText("Net Worth")).toBeInTheDocument();
  });

  it("shows Dashboard tab as selected by default", () => {
    render(<InvestRoute />, { wrapper: createWrapper() });
    const dashboardTab = screen.getByRole("tab", { name: /Dashboard/i });
    expect(dashboardTab).toHaveAttribute("aria-selected", "true");
  });

  it("switches to the Shareholding panel when the Shareholding tab is selected", async () => {
    const user = userEvent.setup();
    render(<InvestRoute />, { wrapper: createWrapper() });

    await user.click(screen.getByRole("tab", { name: /Shareholding/i }));

    expect(screen.getByRole("tab", { name: /Shareholding/i })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    await waitFor(() => {
      expect(screen.getByText("Shareholding Pattern")).toBeInTheDocument();
    });
    expect(screen.queryByText("Portfolio Allocation")).not.toBeInTheDocument();
  });
});
