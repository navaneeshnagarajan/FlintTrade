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

vi.mock("@/components/ui/DemoBanner", () => ({
  DemoBanner: () => <div data-testid="demo-banner">Demo mode</div>,
}));

vi.mock("@/components/motion/StaggeredList", () => ({
  StaggeredList: ({ children, className }: { children: React.ReactNode; className?: string }) => (
    <div className={className}>{children}</div>
  ),
}));

vi.mock("../../InvestContext", () => ({
  useInvest: () => ({
    holdings: [
      { symbol: "RELIANCE", exchange: "NSE", quantity: 50, averagePrice: 2450, ltp: 2520, pnl: 3500, pnlPercent: 2.86 },
      { symbol: "INFY", exchange: "NSE", quantity: 30, averagePrice: 1500, ltp: 1475, pnl: -750, pnlPercent: -1.67 },
    ],
    isLoading: false,
    isError: false,
  }),
}));

import { SectorTab } from "../SectorTab";

describe("SectorTab", () => {
  it("renders sector allocation through Flint primitives", () => {
    render(<SectorTab />);

    expect(screen.getByText("Sector Allocation")).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "Sector allocation donut" })).toBeInTheDocument();
  });
});
