/**
 * SectorTab.test.tsx - render tests for the Invest sector allocation tab.
 */

import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";

vi.mock("@/stores/themeStore", () => ({
  useThemeStore: Object.assign(
    (selector: (s: Record<string, unknown>) => unknown) =>
      selector({
        glass: { enabled: false, blur: 12, transparency: 20 },
        activeThemeId: "graphite",
        mode: "dark",
        customThemes: [],
        getActiveTheme: () => ({
          id: "graphite",
          name: "Graphite",
          dark: { colors: { card: "#16161f", border: "#2a2a3a", cardHover: "#1e1e2e" }, glass: { blur: 12, minOpacity: 0.8 } },
          light: { colors: { card: "#ffffff", border: "#e5e7eb", cardHover: "#f9fafb" }, glass: { blur: 12, minOpacity: 0.8 } },
        }),
        getResolvedMode: () => "dark",
      }),
    { getState: () => ({ glass: { enabled: false } }) },
  ),
}));

vi.mock("@/lib/cinematicThemes", () => ({
  getResolvedVariant: () => ({
    colors: { card: "#16161f", border: "#2a2a3a", cardHover: "#1e1e2e" },
    glass: { blur: 12, minOpacity: 0.8 },
  }),
}));

vi.mock("@/components/motion/StaggeredList", () => ({
  StaggeredList: ({ children, className }: { children: React.ReactNode; className?: string }) => (
    <div className={className}>{children}</div>
  ),
}));

const investState = vi.hoisted(() => ({
  holdings: [
    { symbol: "RELIANCE", exchange: "NSE", quantity: 50, averagePrice: 2450, ltp: 2520, pnl: 3500, pnlPercent: 2.86 },
    { symbol: "INFY", exchange: "NSE", quantity: 30, averagePrice: 1500, ltp: 1475, pnl: -750, pnlPercent: -1.67 },
  ],
  isLoading: false,
  isError: false,
  isSampleData: false,
}));

vi.mock("../../InvestContext", () => ({
  useInvest: () => investState,
}));

import { useModeStore } from "@/stores/modeStore";
import { SectorTab } from "../SectorTab";

const LIVE_HEADER = "Portfolio value distribution across NSE sectors, derived from your live holdings.";

describe("SectorTab", () => {
  it("renders sector allocation through Flint primitives", () => {
    investState.isSampleData = false;
    render(<SectorTab />);

    expect(screen.getByText("Sector Allocation")).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "Sector allocation donut" })).toBeInTheDocument();
  });

  it("shows one Example chip and example wording on a sample book", () => {
    useModeStore.setState({ mode: "explore" });
    investState.isSampleData = true;
    render(<SectorTab />);

    expect(screen.getAllByTestId("example-chip")).toHaveLength(1);
    expect(screen.getByText("Example sector split. Connect a broker to see yours.")).toBeInTheDocument();
    expect(screen.getByText("Example data. Not from your holdings.")).toBeInTheDocument();
    expect(screen.queryByText(LIVE_HEADER)).not.toBeInTheDocument();
    expect(screen.queryByText(/Data sourced from live holdings/)).not.toBeInTheDocument();
  });

  it("keeps live holdings wording and no Example chip when the book is not sample data", () => {
    useModeStore.setState({ mode: "practice" });
    investState.isSampleData = false;
    render(<SectorTab />);

    expect(screen.getByText(LIVE_HEADER)).toBeInTheDocument();
    expect(screen.getByText(/Data sourced from live holdings via your active broker data source/)).toBeInTheDocument();
    expect(screen.queryByTestId("example-chip")).not.toBeInTheDocument();
    expect(screen.queryByText("Example sector split. Connect a broker to see yours.")).not.toBeInTheDocument();
    expect(screen.queryByText("Example data. Not from your holdings.")).not.toBeInTheDocument();
  });
});
