/**
 * MarketIntelligenceTool.test.tsx
 *
 * Tests for the Market Intelligence canvas tool.
 * Verifies rendering, heading, and key UI elements.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, within } from "@testing-library/react";
import "@testing-library/jest-dom";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

const marketIntelMocks = vi.hoisted(() => ({
  gexData: undefined as
    | Array<{
        strike: number;
        call_gamma: number;
        put_gamma: number;
        net_gamma: number;
        call_oi: number;
        put_oi: number;
      }>
    | undefined,
  ivSmileData: undefined as
    | Array<{
        strike: number;
        call_iv: number;
        put_iv: number;
        moneyness: number;
      }>
    | undefined,
  maxPainData: undefined as
    | {
        max_pain_strike: number;
        strikes: Array<{
          strike: number;
          call_oi: number;
          put_oi: number;
          call_pain: number;
          put_pain: number;
          total_pain: number;
        }>;
      }
    | undefined,
  oiProfileData: undefined as
    | Array<{
        strike: number;
        type: "CE" | "PE";
        oi: number;
        oi_delta_d: number;
        ltp: number;
      }>
    | undefined,
}));

// Mock market intel hooks
vi.mock("@/hooks/useMarketIntel", () => ({
  useGex: () => ({
    data: marketIntelMocks.gexData,
    isLoading: false,
    isError: false,
    refetch: vi.fn(),
  }),
  useIVSmile: () => ({
    data: marketIntelMocks.ivSmileData,
    isLoading: false,
    isError: false,
    refetch: vi.fn(),
  }),
  useMaxPain: () => ({
    data: marketIntelMocks.maxPainData,
    isLoading: false,
    isError: false,
    refetch: vi.fn(),
  }),
  useOIProfile: () => ({
    data: marketIntelMocks.oiProfileData,
    isLoading: false,
    isError: false,
    refetch: vi.fn(),
  }),
}));

// Mock API calls
vi.mock("@/services/api", () => ({
  getExpiry: vi.fn().mockResolvedValue([]),
}));

// ---------------------------------------------------------------------------
// Import component under test (after mocks)
// ---------------------------------------------------------------------------

import MarketIntelligenceTool from "../MarketIntelligenceTool";
import { useModeStore } from "@/stores/modeStore";

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("MarketIntelligenceTool", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    marketIntelMocks.gexData = undefined;
    marketIntelMocks.ivSmileData = undefined;
    marketIntelMocks.maxPainData = undefined;
    marketIntelMocks.oiProfileData = undefined;
    useModeStore.setState({ mode: "explore" });
  });

  it("renders without crashing", () => {
    const { container } = render(<MarketIntelligenceTool />);
    expect(container).toBeInTheDocument();
  });

  it("shows the Market Intelligence heading", () => {
    render(<MarketIntelligenceTool />);
    expect(screen.getByText("Market Intelligence")).toBeInTheDocument();
  });

  it("shows the Sample Data badge for sample-data tabs", () => {
    render(<MarketIntelligenceTool />);
    // The default tab (breadth) uses sample data
    expect(screen.getByText("Sample Data")).toBeInTheDocument();
  });

  it("labels option-intel tabs as sample data in explore mode", () => {
    render(<MarketIntelligenceTool />);

    fireEvent.click(screen.getByRole("button", { name: "GEX" }));

    expect(screen.getByText("Sample Data")).toBeInTheDocument();
    expect(screen.queryByText("Live")).not.toBeInTheDocument();
  });

  it("renders market breadth distribution through the shared stacked-bar primitive", () => {
    render(<MarketIntelligenceTool />);

    expect(screen.getByRole("img", { name: "Market breadth by index" })).toHaveAttribute(
      "data-flint-chart",
      "stacked-bar",
    );
  });

  it("renders India VIX range through the shared linear-meter primitive", () => {
    render(<MarketIntelligenceTool />);

    fireEvent.click(screen.getByRole("button", { name: "India VIX" }));

    expect(screen.getByRole("img", { name: "India VIX 52-week range" })).toHaveAttribute(
      "data-flint-chart",
      "linear-meter",
    );
  });

  it("renders delivery percentages through the shared linear-meter primitive", () => {
    render(<MarketIntelligenceTool />);

    fireEvent.click(screen.getByRole("button", { name: "Delivery Data" }));

    expect(screen.getByRole("img", { name: "HDFCBANK delivery percentage" })).toHaveAttribute(
      "data-flint-chart",
      "linear-meter",
    );
  });

  it("sorts delivery rows through accessible table header controls", () => {
    render(<MarketIntelligenceTool />);

    fireEvent.click(screen.getByRole("button", { name: "Delivery Data" }));
    fireEvent.click(screen.getByRole("button", { name: "Sort by Symbol" }));
    fireEvent.click(screen.getByRole("button", { name: "Sort by Symbol" }));

    const rows = screen.getAllByRole("row");
    expect(within(rows[0]).getByText("Symbol")).toBeInTheDocument();
    expect(within(rows[1]).getByText("AXISBANK")).toBeInTheDocument();
  });

  it("renders sector heatmap through the shared weighted-heatmap primitive", () => {
    render(<MarketIntelligenceTool />);

    fireEvent.click(screen.getByRole("button", { name: "Sector Heatmap" }));

    expect(screen.getByRole("list", { name: "Sector heatmap by 1D return and market cap" })).toHaveAttribute(
      "data-flint-chart",
      "weighted-heatmap",
    );
  });

  it("renders IV Smile through the shared multi-line primitive", () => {
    marketIntelMocks.ivSmileData = [
      { strike: 23400, call_iv: 12.4, put_iv: 16.8, moneyness: -0.8 },
      { strike: 23500, call_iv: 11.8, put_iv: 13.2, moneyness: 0 },
      { strike: 23600, call_iv: 14.1, put_iv: 12.6, moneyness: 0.7 },
    ];
    render(<MarketIntelligenceTool />);

    fireEvent.click(screen.getByRole("button", { name: "IV Smile" }));

    expect(screen.getByRole("img", { name: "IV Smile call and put volatility by strike" })).toHaveAttribute(
      "data-flint-chart",
      "multi-line",
    );
  });

  it("renders max pain distribution through the shared stacked-bar primitive", () => {
    marketIntelMocks.maxPainData = {
      max_pain_strike: 23500,
      strikes: [
        { strike: 23400, call_oi: 120000, put_oi: 98000, call_pain: 900000, put_pain: 300000, total_pain: 1200000 },
        { strike: 23500, call_oi: 140000, put_oi: 125000, call_pain: 600000, put_pain: 600000, total_pain: 1200000 },
        { strike: 23600, call_oi: 94000, put_oi: 152000, call_pain: 250000, put_pain: 750000, total_pain: 1000000 },
      ],
    };
    render(<MarketIntelligenceTool />);

    fireEvent.click(screen.getByRole("button", { name: "Max Pain" }));

    expect(screen.getByRole("img", { name: "Max pain distribution across strikes" })).toHaveAttribute(
      "data-flint-chart",
      "stacked-bar",
    );
  });

  it("renders GEX through the shared diverging-bar primitive", () => {
    marketIntelMocks.gexData = [
      { strike: 23400, call_gamma: 0.24, put_gamma: -0.18, net_gamma: 0.06, call_oi: 120000, put_oi: 98000 },
      { strike: 23500, call_gamma: 0.16, put_gamma: -0.42, net_gamma: -0.26, call_oi: 140000, put_oi: 125000 },
    ];
    render(<MarketIntelligenceTool />);

    fireEvent.click(screen.getByRole("button", { name: "GEX" }));

    expect(screen.getByRole("list", { name: "Net gamma exposure by strike" })).toHaveAttribute(
      "data-flint-chart",
      "diverging-bar-list",
    );
  });

  it("renders OI profile through the shared diverging-bar primitive", () => {
    marketIntelMocks.oiProfileData = [
      { strike: 23400, type: "PE", oi: 120000, oi_delta_d: 4000, ltp: 82.5 },
      { strike: 23400, type: "CE", oi: 80000, oi_delta_d: -2400, ltp: 126.5 },
      { strike: 23500, type: "PE", oi: 90000, oi_delta_d: 3200, ltp: 112.5 },
      { strike: 23500, type: "CE", oi: 140000, oi_delta_d: 5200, ltp: 72.5 },
    ];
    render(<MarketIntelligenceTool />);

    fireEvent.click(screen.getByRole("button", { name: "OI Profile" }));

    expect(screen.getByRole("list", { name: "OI profile by strike" })).toHaveAttribute(
      "data-flint-chart",
      "diverging-bar-list",
    );
  });
});
