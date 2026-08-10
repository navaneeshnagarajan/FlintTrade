/**
 * PortfolioAllocationWidget.test.tsx
 *
 * Tests: render, view toggle, donut SVG, legend, sample data.
 */

import { describe, it, expect, vi, beforeAll, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import "@testing-library/jest-dom";

beforeAll(() => {
  global.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
});

vi.mock("@/hooks/useTrackBehavior", () => ({
  useTrackBehavior: () => vi.fn(),
}));

vi.mock("@/hooks/useBrokerAccounts", () => ({
  useBrokerAccounts: () => ({ data: [] }),
}));

const mockGetPositionbook = vi.hoisted(() => vi.fn());
const mockGetHoldings = vi.hoisted(() => vi.fn());
vi.mock("@/services/api", () => ({
  getPositionbook: (...args: unknown[]) => mockGetPositionbook(...args),
  getHoldings: (...args: unknown[]) => mockGetHoldings(...args),
}));

import PortfolioAllocationWidget from "../PortfolioAllocationWidget";
import {
  resetAccountRuntime,
  setAccountRuntime,
} from "@/test-utils/accountQueryHarness";

function wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

beforeEach(() => {
  setAccountRuntime({ accounts: [], mode: "explore" });
  mockGetPositionbook.mockReset();
  mockGetHoldings.mockReset();
  mockGetPositionbook.mockResolvedValue([]);
  mockGetHoldings.mockResolvedValue([]);
});

afterEach(() => {
  resetAccountRuntime();
});

describe("PortfolioAllocationWidget", () => {
  it("renders the widget header", () => {
    render(<PortfolioAllocationWidget />, { wrapper });
    expect(screen.getByText("Portfolio Allocation")).toBeTruthy();
  });

  it("shows sample data badge when disconnected", () => {
    render(<PortfolioAllocationWidget />, { wrapper });
    expect(screen.getByText("Sample")).toBeTruthy();
  });

  it("renders the donut chart", () => {
    render(<PortfolioAllocationWidget />, { wrapper });
    expect(screen.getByRole("img", { name: "Portfolio allocation donut chart" })).toBeTruthy();
  });

  it("renders allocation through the shared Flint donut primitive", () => {
    render(<PortfolioAllocationWidget />, { wrapper });
    const chart = screen.getByRole("img", { name: "Portfolio allocation donut chart" });
    expect(chart).toHaveAttribute("data-flint-chart", "donut");
    expect(chart.getAttribute("style")).toContain("conic-gradient");
    expect(chart.querySelector("svg")).not.toBeInTheDocument();
  });

  it("renders Asset Class and Sector view tabs", () => {
    render(<PortfolioAllocationWidget />, { wrapper });
    expect(screen.getByText("Asset Class")).toBeTruthy();
    expect(screen.getByText("Sector")).toBeTruthy();
  });

  it("switches to Sector view when tab is clicked", () => {
    render(<PortfolioAllocationWidget />, { wrapper });
    const sectorTab = screen.getByText("Sector");
    fireEvent.click(sectorTab);
    expect(sectorTab.getAttribute("aria-selected")).toBe("true");
    expect(screen.getByText("Banking")).toBeTruthy();
  });

  it("renders sample asset class slices in the legend", () => {
    render(<PortfolioAllocationWidget />, { wrapper });
    expect(screen.getByText("Equity")).toBeTruthy();
    expect(screen.getByText("F&O")).toBeTruthy();
    expect(screen.getByText("Commodity")).toBeTruthy();
  });

  it("renders the allocation breakdown list", () => {
    render(<PortfolioAllocationWidget />, { wrapper });
    expect(screen.getByRole("list", { name: "Allocation breakdown" })).toBeTruthy();
  });

  it("renders percentages in the legend", () => {
    render(<PortfolioAllocationWidget />, { wrapper });
    const pctPattern = /\d+\.\d+%/;
    const pcts = screen.getAllByText(pctPattern);
    expect(pcts.length).toBeGreaterThan(0);
  });

  it("shows an honest empty state for a connected portfolio with no allocation", async () => {
    setAccountRuntime({ mode: "live" });

    render(<PortfolioAllocationWidget />, { wrapper });

    expect(await screen.findByText("No portfolio allocation data")).toBeInTheDocument();
    expect(screen.queryByText("Sample")).not.toBeInTheDocument();
    expect(screen.queryByRole("img", { name: "Portfolio allocation donut chart" })).not.toBeInTheDocument();
    expect(screen.queryByText("Equity")).not.toBeInTheDocument();

    fireEvent.click(screen.getByText("Sector"));
    expect(screen.getByText("No portfolio allocation data")).toBeInTheDocument();
    expect(screen.queryByText("Banking")).not.toBeInTheDocument();
    expect(screen.queryByRole("img", { name: "Portfolio allocation donut chart" })).not.toBeInTheDocument();
  });

  it("reads and labels the Practice sandbox without a live broker", async () => {
    setAccountRuntime({ accounts: [], mode: "practice" });
    mockGetPositionbook.mockResolvedValue([
      { symbol: "SBIN", exchange: "NSE", product: "MIS", quantity: 2, averagePrice: 800, ltp: 810, pnl: 20 },
    ]);

    render(<PortfolioAllocationWidget />, { wrapper });

    expect(await screen.findByText("Practice")).toBeInTheDocument();
    expect(await screen.findByText("Equity")).toBeInTheDocument();
    expect(mockGetPositionbook).toHaveBeenCalled();
  });
});
