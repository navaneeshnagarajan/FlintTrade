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
import MarketBreadthWidget from "../MarketBreadthWidget";

const mockUseBrokerConnected = useBrokerConnected as ReturnType<typeof vi.fn>;

beforeEach(() => {
  global.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
});

describe("MarketBreadthWidget", () => {
  it("renders widget header with title", () => {
    mockUseBrokerConnected.mockReturnValue(false);
    render(<MarketBreadthWidget />);
    expect(screen.getByText("Market Breadth")).toBeTruthy();
  });

  it("shows sample badge when broker is disconnected", () => {
    mockUseBrokerConnected.mockReturnValue(false);
    render(<MarketBreadthWidget />);
    expect(screen.getByText("Sample")).toBeTruthy();
  });

  it("does not show sample badge when broker is connected", () => {
    // Stub fetch to avoid unresolved promises in test environment
    global.fetch = vi.fn().mockImplementation(() => new Promise(() => {}));
    mockUseBrokerConnected.mockReturnValue(true);
    render(<MarketBreadthWidget />);
    expect(screen.queryByText("Sample")).toBeNull();
  });

  it("renders A/D ratio section with Advances and Declines labels", () => {
    mockUseBrokerConnected.mockReturnValue(false);
    render(<MarketBreadthWidget />);
    expect(screen.getAllByText("Advances").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Declines").length).toBeGreaterThan(0);
    expect(screen.getByText("A/D Ratio")).toBeTruthy();
  });

  it("renders McClellan Oscillator and Breadth Thrust sections", () => {
    mockUseBrokerConnected.mockReturnValue(false);
    render(<MarketBreadthWidget />);
    expect(screen.getByText(/McClellan Osc/i)).toBeTruthy();
    expect(screen.getByText(/Breadth Thrust/i)).toBeTruthy();
  });

  it("renders 52-week highs vs lows section", () => {
    mockUseBrokerConnected.mockReturnValue(false);
    render(<MarketBreadthWidget />);
    expect(screen.getByText(/52-Week Highs vs Lows/i)).toBeTruthy();
    expect(screen.getByText("New Highs")).toBeTruthy();
    expect(screen.getByText("New Lows")).toBeTruthy();
  });

  it("refresh button is disabled when broker is disconnected", () => {
    mockUseBrokerConnected.mockReturnValue(false);
    render(<MarketBreadthWidget />);
    const btn = screen.getByRole("button", { name: /refresh market breadth/i });
    expect(btn).toBeDisabled();
  });
});
