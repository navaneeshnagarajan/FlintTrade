/**
 * PortfolioAllocationWidget.test.tsx
 *
 * Tests: render, view toggle, donut SVG, legend, sample data.
 */

import { describe, it, expect, vi, beforeAll } from "vitest";
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

vi.mock("@/hooks/useBrokerConnected", () => ({
  useBrokerConnected: vi.fn().mockReturnValue(false),
}));

vi.mock("@/services/api", () => ({
  getPositionbook: vi.fn(() => Promise.resolve([])),
  getHoldings: vi.fn(() => Promise.resolve([])),
}));

import PortfolioAllocationWidget from "../PortfolioAllocationWidget";

function wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

describe("PortfolioAllocationWidget", () => {
  it("renders the widget header", () => {
    render(<PortfolioAllocationWidget />, { wrapper });
    expect(screen.getByText("Portfolio Allocation")).toBeTruthy();
  });

  it("shows sample data badge when disconnected", () => {
    render(<PortfolioAllocationWidget />, { wrapper });
    expect(screen.getByText("sample data")).toBeTruthy();
  });

  it("renders the donut SVG chart", () => {
    render(<PortfolioAllocationWidget />, { wrapper });
    expect(screen.getByRole("img", { name: "Portfolio allocation donut chart" })).toBeTruthy();
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
});
