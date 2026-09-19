/**
 * HoldingsTab.test.tsx — Render tests for the holdings table tab.
 *
 * FT-TRADE-010: the table must render the same rows the header badge
 * counts. A connected empty book stays empty — no sample fallback.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { act, fireEvent, render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";
import type { Holding } from "@/types/api";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

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

vi.mock("@/lib/exportUtils", () => ({
  exportToCSV: vi.fn(),
  printCurrentView: vi.fn(),
}));

const SAMPLE_ROWS: Holding[] = [
  { symbol: "RELIANCE", exchange: "NSE", quantity: 50, averagePrice: 2450, ltp: 2520, pnl: 3500, pnlPercent: 2.86 },
  { symbol: "TCS", exchange: "NSE", quantity: 25, averagePrice: 3800, ltp: 3920, pnl: 3000, pnlPercent: 3.16 },
];

const investState = vi.hoisted(() => ({
  holdings: [] as Holding[],
  summary: {
    currentValue: 224000,
    totalInvested: 217500,
    totalPnl: 6500,
    totalPnlPercent: 2.99,
    availableCash: 50000,
    sectorCount: 2,
    holdingCount: 2,
  },
  isLoading: false,
  isError: false,
  isSampleData: false,
  refetchHoldings: vi.fn(),
}));

vi.mock("../../InvestContext", () => ({
  useInvest: () => investState,
}));

// ---------------------------------------------------------------------------
// Import after mocks
// ---------------------------------------------------------------------------

import { HoldingsTab } from "../HoldingsTab";

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("HoldingsTab", () => {
  beforeEach(() => {
    investState.holdings = SAMPLE_ROWS;
    investState.isLoading = false;
    investState.isError = false;
    investState.isSampleData = false;
    investState.summary.holdingCount = SAMPLE_ROWS.length;
    investState.refetchHoldings.mockClear();
  });

  it("renders the holdings table with symbols", () => {
    render(<HoldingsTab />);
    expect(screen.getByText("RELIANCE")).toBeInTheDocument();
    expect(screen.getByText("TCS")).toBeInTheDocument();
  });

  it("shows the stock count and toolbar buttons", () => {
    render(<HoldingsTab />);
    expect(screen.getByText("2 stocks")).toBeInTheDocument();
    expect(screen.getByText("Export CSV")).toBeInTheDocument();
    expect(screen.getByText("Refresh")).toBeInTheDocument();
  });

  it("shows stacked P&L cards instead of the clipped table at ~390px", () => {
    let resizeCallback: ResizeObserverCallback | null = null;
    vi.stubGlobal(
      "ResizeObserver",
      class ResizeObserver {
        constructor(callback: ResizeObserverCallback) {
          resizeCallback = callback;
        }
        observe = vi.fn();
        disconnect = vi.fn();
        unobserve = vi.fn();
      },
    );

    render(<HoldingsTab />);

    act(() => {
      resizeCallback?.(
        [{ contentRect: { width: 390, height: 700 } } as ResizeObserverEntry],
        {} as ResizeObserver,
      );
    });

    const cards = screen.getByRole("list", { name: "Holdings" });
    expect(cards).toHaveAttribute("data-layout", "cards");
    expect(cards).toHaveTextContent("RELIANCE");
    expect(cards).toHaveTextContent("₹3,500");
    expect(cards).toHaveTextContent("+2.86%");
    expect(screen.queryByRole("columnheader", { name: /Avg Price/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Holdings totals")).toHaveTextContent("₹6,500");
    vi.unstubAllGlobals();
  });

  it("shows N stocks matching the sample rows currently in the table", () => {
    investState.holdings = SAMPLE_ROWS;
    investState.isSampleData = true;

    render(<HoldingsTab />);

    expect(screen.getByText(`${SAMPLE_ROWS.length} stocks`)).toBeInTheDocument();
    expect(screen.getByText("RELIANCE")).toBeInTheDocument();
    expect(screen.getByText("TCS")).toBeInTheDocument();
    expect(screen.getByTestId("demo-banner")).toBeInTheDocument();
  });

  it("shows an honest empty state with no sample rows when the connected book is empty", () => {
    investState.holdings = [];
    investState.isSampleData = false;

    render(<HoldingsTab />);

    expect(screen.getByText("No holdings")).toBeInTheDocument();
    expect(screen.queryByText("RELIANCE")).not.toBeInTheDocument();
    expect(screen.queryByText("TCS")).not.toBeInTheDocument();
    expect(screen.queryByText(/stocks$/)).not.toBeInTheDocument();
    expect(screen.queryByTestId("demo-banner")).not.toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("shows failure and Refresh when the broker holdings query errored with an empty book", () => {
    investState.holdings = [];
    investState.isError = true;
    investState.isSampleData = false;

    render(<HoldingsTab />);

    expect(screen.getByText("Failed to load holdings")).toBeInTheDocument();
    expect(screen.getByText("Refresh")).toBeInTheDocument();
    expect(screen.queryByText("No holdings")).not.toBeInTheDocument();
    expect(screen.queryByText("RELIANCE")).not.toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    expect(screen.queryByTestId("demo-banner")).not.toBeInTheDocument();

    fireEvent.click(screen.getByText("Refresh"));
    expect(investState.refetchHoldings).toHaveBeenCalledTimes(1);
  });
});
