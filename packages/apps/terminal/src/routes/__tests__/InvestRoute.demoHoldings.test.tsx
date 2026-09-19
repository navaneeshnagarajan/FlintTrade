/**
 * FT-DEMO-001 / FT-TRADE-010 — Investor Dashboard header holdings badge.
 *
 * Practice/Explore with no broker must count the same sample book the
 * Holdings table lists, and disclose it with a Sample chip. A connected
 * empty book stays at 0 with no sample rows.
 */

import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
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

const brokerConnected = vi.hoisted(() => ({ current: false }));

vi.mock("@/hooks/useBrokerConnected", () => ({
  useBrokerConnected: () => brokerConnected.current,
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
  brokerConnected.current = false;
  useModeStore.setState({ mode: "explore" });
});

describe("InvestRoute header holdings badge (FT-DEMO-001 / FT-TRADE-010)", () => {
  it("shows the demo holdings count and a Sample chip in explore mode", () => {
    useModeStore.setState({ mode: "explore" });
    renderInvest();

    const expected = getDemoHoldings();
    expect(screen.getByText(`${expected.length} holdings`)).toBeInTheDocument();
    expect(screen.getByText("Sample")).toBeInTheDocument();
  });

  it("matches header N, Sample chip, and Holdings table rows in practice with no broker", async () => {
    useModeStore.setState({ mode: "practice" });
    brokerConnected.current = false;
    const user = userEvent.setup();
    renderInvest();

    const expected = getDemoHoldings();
    expect(screen.getByText(`${expected.length} holdings`)).toBeInTheDocument();
    expect(screen.getByText("Sample")).toBeInTheDocument();

    await user.click(screen.getByRole("tab", { name: /Holdings/i }));

    await waitFor(() => {
      expect(screen.getByText(`${expected.length} stocks`)).toBeInTheDocument();
    });
    expect(screen.getByText(expected[0].symbol)).toBeInTheDocument();
  });

  it("shows 0 holdings in live mode when the broker book is empty", () => {
    useModeStore.setState({ mode: "live" });
    brokerConnected.current = true;
    renderInvest();

    expect(screen.getByText("0 holdings")).toBeInTheDocument();
    expect(screen.queryByText("Sample")).not.toBeInTheDocument();
  });

  it("keeps the Holdings table empty when a connected broker has no positions", async () => {
    useModeStore.setState({ mode: "live" });
    brokerConnected.current = true;
    const user = userEvent.setup();
    renderInvest();

    await user.click(screen.getByRole("tab", { name: /Holdings/i }));

    await waitFor(() => {
      expect(screen.getByText("No holdings")).toBeInTheDocument();
    });
    expect(screen.getByText("0 holdings")).toBeInTheDocument();
    expect(screen.queryByText("Sample")).not.toBeInTheDocument();
    expect(screen.queryByText("RELIANCE")).not.toBeInTheDocument();
    expect(screen.queryByText(/stocks$/)).not.toBeInTheDocument();
  });
});
