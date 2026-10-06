import { describe, it, expect, vi, beforeEach } from "vitest";
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router";

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

vi.mock("@/components/magicui/animated-counter", () => ({
  AnimatedCounter: ({
    value,
    formatter,
    className,
  }: {
    value: number;
    formatter?: (v: number) => string;
    className?: string;
  }) => <span className={className}>{formatter ? formatter(value) : value}</span>,
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

async function renderInvestRoute(
  loadTab: () => Promise<unknown> = () => import("../invest/tabs/DashboardTab"),
) {
  // Keep the real lazy tab, but finish its import before React cleanup and worker teardown.
  await act(async () => {
    render(<InvestRoute />, { wrapper: createWrapper() });
    await loadTab();
  });
}

describe("InvestRoute", () => {
  beforeEach(() => {
    window.history.replaceState(null, "", "/invest");
  });

  it("renders the Invest heading, matching its sidebar label", async () => {
    await renderInvestRoute();
    expect(screen.getByRole("heading", { level: 1, name: "Invest" })).toBeInTheDocument();
    expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
  });

  it("shows five Invest groups instead of the flat tab row", async () => {
    await renderInvestRoute();
    const groups = screen.getByRole("tablist", { name: "Invest sections" });
    const tabs = within(groups).getAllByRole("tab");
    expect(tabs.map((tab) => tab.textContent)).toEqual([
      "Overview",
      "Holdings",
      "Analyse",
      "Discover",
      "Tax",
    ]);
    expect(within(groups).getByRole("tab", { name: "Overview" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    const views = screen.getByRole("tablist", { name: "Overview views" });
    expect(within(views).getByRole("tab", { name: "Dashboard" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    expect(within(views).getByRole("tab", { name: "Net Worth" })).toBeInTheDocument();
    expect(within(views).getByRole("tab", { name: "Goals" })).toBeInTheDocument();
    expect(within(views).queryByRole("tab", { name: "SIPs" })).not.toBeInTheDocument();
  });

  it("shows Dashboard as the selected Overview view by default", async () => {
    await renderInvestRoute();
    const views = screen.getByRole("tablist", { name: "Overview views" });
    expect(within(views).getByRole("tab", { name: "Dashboard" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
  });

  it("opens Shareholding under Analyse", async () => {
    const user = userEvent.setup();
    await renderInvestRoute();

    await user.click(screen.getByRole("tab", { name: "Analyse" }));
    await act(async () => {
      await import("../invest/tabs/SectorTab");
    });
    const views = screen.getByRole("tablist", { name: "Analyse views" });
    await user.click(within(views).getByRole("tab", { name: "Shareholding" }));
    await act(async () => {
      await import("../invest/tabs/ShareholdingTab");
    });

    expect(within(views).getByRole("tab", { name: "Shareholding" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    await waitFor(() => {
      expect(screen.getByText("Shareholding Pattern")).toBeInTheDocument();
    });
    expect(screen.queryByText("Portfolio Allocation")).not.toBeInTheDocument();
  });

  it.each([
    ["#holdings", "Holdings", "Holdings", () => import("../invest/tabs/HoldingsTab")],
    ["#sip", "Holdings", "SIPs", () => import("../invest/tabs/SipTab")],
    ["#networth", "Overview", "Net Worth", () => import("../invest/tabs/NetWorthTab")],
    ["#mf-optimizer", "Discover", "MF Optimizer", () => import("../invest/tabs/MfOptimizerTab")],
    ["#sector-rotation", "Analyse", "Sector Rotation", () => import("../invest/tabs/SectorRotationTab")],
    ["#overview", "Overview", "Dashboard", () => import("../invest/tabs/DashboardTab")],
    ["#tax", "Tax", "Tax", () => import("../invest/tabs/TaxTab")],
  ] as const)("redirects %s to the %s group and %s view", async (hash, groupName, viewName, loadTab) => {
    window.history.replaceState(null, "", `/invest${hash}`);

    await renderInvestRoute(loadTab);

    const groups = screen.getByRole("tablist", { name: "Invest sections" });
    expect(within(groups).getByRole("tab", { name: groupName })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    if (groupName !== viewName) {
      const views = screen.getByRole("tablist", { name: `${groupName} views` });
      expect(within(views).getByRole("tab", { name: viewName })).toHaveAttribute(
        "aria-selected",
        "true",
      );
    }
  });

  it("keeps Dashboard selected for an unknown Invest hash", async () => {
    window.history.replaceState(null, "", "/invest#not-a-tab");

    await renderInvestRoute();

    const views = screen.getByRole("tablist", { name: "Overview views" });
    expect(within(views).getByRole("tab", { name: "Dashboard" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
  });

  it("syncs the active group when the Invest hash changes", async () => {
    window.history.replaceState(null, "", "/invest#sip");

    await renderInvestRoute(() => import("../invest/tabs/SipTab"));

    expect(within(screen.getByRole("tablist", { name: "Holdings views" })).getByRole("tab", { name: "SIPs" })).toHaveAttribute(
      "aria-selected",
      "true",
    );

    await act(async () => {
      window.location.hash = "#holdings";
      window.dispatchEvent(new HashChangeEvent("hashchange"));
      await import("../invest/tabs/HoldingsTab");
    });

    const groups = screen.getByRole("tablist", { name: "Invest sections" });
    expect(within(groups).getByRole("tab", { name: "Holdings" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    expect(within(groups).getByRole("tab", { name: "Overview" })).toHaveAttribute(
      "aria-selected",
      "false",
    );
    expect(within(screen.getByRole("tablist", { name: "Holdings views" })).getByRole("tab", { name: "Holdings" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
  });
});
