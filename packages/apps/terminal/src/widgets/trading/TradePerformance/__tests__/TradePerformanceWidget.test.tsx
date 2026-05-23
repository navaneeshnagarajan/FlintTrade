import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

vi.mock("@/hooks/useBrokerConnected", () => ({
  useBrokerConnected: vi.fn().mockReturnValue(false),
}));

vi.mock("@/hooks/useTrackBehavior", () => ({
  useTrackBehavior: () => vi.fn(),
}));

import { useBrokerConnected } from "@/hooks/useBrokerConnected";
import TradePerformanceWidget from "../TradePerformanceWidget";

const mockUseBrokerConnected = useBrokerConnected as ReturnType<typeof vi.fn>;

beforeEach(() => {
  global.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
});

describe("TradePerformanceWidget", () => {
  it("renders the widget title", () => {
    render(<TradePerformanceWidget />);
    expect(screen.getByText("Trade Performance")).toBeTruthy();
  });

  it("shows Sample badge when disconnected", () => {
    mockUseBrokerConnected.mockReturnValue(false);
    render(<TradePerformanceWidget />);
    expect(screen.getByText("Sample")).toBeTruthy();
  });

  it("hides Sample badge when connected", () => {
    mockUseBrokerConnected.mockReturnValue(true);
    render(<TradePerformanceWidget />);
    expect(screen.queryByText("Sample")).toBeNull();
  });

  it("renders the equity curve SVG", () => {
    render(<TradePerformanceWidget />);
    expect(screen.getByRole("img", { name: /equity curve chart/i })).toBeTruthy();
  });

  it("renders key metrics section with Win Rate", () => {
    render(<TradePerformanceWidget />);
    expect(screen.getByText("Win Rate")).toBeTruthy();
  });

  it("renders key metrics section with Profit Factor", () => {
    render(<TradePerformanceWidget />);
    expect(screen.getByText("Profit Factor")).toBeTruthy();
  });

  it("renders streak tracker section", () => {
    render(<TradePerformanceWidget />);
    expect(screen.getByText("Current")).toBeTruthy();
    expect(screen.getByText("Best Win")).toBeTruthy();
    expect(screen.getByText("Worst Loss")).toBeTruthy();
  });

  it("renders monthly returns heatmap with months", () => {
    render(<TradePerformanceWidget />);
    expect(screen.getByLabelText("Monthly returns heatmap")).toBeTruthy();
  });

  it("renders day distribution chart", () => {
    render(<TradePerformanceWidget />);
    expect(screen.getByRole("img", { name: /trade distribution by day/i })).toBeTruthy();
  });

  it("renders Expectancy metric", () => {
    render(<TradePerformanceWidget />);
    expect(screen.getByText("Expectancy")).toBeTruthy();
  });
});
