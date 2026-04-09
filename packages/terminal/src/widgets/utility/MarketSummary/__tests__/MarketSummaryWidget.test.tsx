import { describe, it, expect, vi, beforeAll } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";

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
import MarketSummaryWidget from "../MarketSummaryWidget";

const mockConnected = useBrokerConnected as ReturnType<typeof vi.fn>;

beforeAll(() => {
  global.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
});

// ---------------------------------------------------------------------------
// Widget render tests
// ---------------------------------------------------------------------------

describe("MarketSummaryWidget", () => {
  it("renders widget title", () => {
    mockConnected.mockReturnValue(false);
    render(<MarketSummaryWidget />);
    expect(screen.getByText("Market Summary")).toBeTruthy();
  });

  it("shows Sample badge when disconnected", () => {
    mockConnected.mockReturnValue(false);
    render(<MarketSummaryWidget />);
    expect(screen.getByText("Sample")).toBeTruthy();
  });

  it("does not show Sample badge when connected", () => {
    mockConnected.mockReturnValue(true);
    render(<MarketSummaryWidget />);
    expect(screen.queryByText("Sample")).toBeNull();
  });

  it("renders all four index cards", () => {
    mockConnected.mockReturnValue(false);
    render(<MarketSummaryWidget />);
    expect(screen.getByText("NIFTY")).toBeTruthy();
    expect(screen.getByText("BANKNIFTY")).toBeTruthy();
    expect(screen.getByText("NIFTYIT")).toBeTruthy();
    expect(screen.getByText("INDIA VIX")).toBeTruthy();
  });

  it("renders market breadth section heading", () => {
    mockConnected.mockReturnValue(false);
    render(<MarketSummaryWidget />);
    expect(screen.getByText(/Market Breadth/i)).toBeTruthy();
  });

  it("renders A/D ratio text", () => {
    mockConnected.mockReturnValue(false);
    render(<MarketSummaryWidget />);
    expect(screen.getByText(/A\/D ratio/i)).toBeTruthy();
  });

  it("renders FII/DII section", () => {
    mockConnected.mockReturnValue(false);
    render(<MarketSummaryWidget />);
    expect(screen.getByText("FII Net")).toBeTruthy();
    expect(screen.getByText("DII Net")).toBeTruthy();
  });

  it("renders gainers and losers section", () => {
    mockConnected.mockReturnValue(false);
    render(<MarketSummaryWidget />);
    expect(screen.getByText("Gainers")).toBeTruthy();
    expect(screen.getByText("Losers")).toBeTruthy();
  });

  it("renders sector performance section", () => {
    mockConnected.mockReturnValue(false);
    render(<MarketSummaryWidget />);
    expect(screen.getByText(/Sector Performance/i)).toBeTruthy();
    expect(screen.getByText("IT")).toBeTruthy();
    expect(screen.getByText("Pharma")).toBeTruthy();
  });

  it("refresh button is present and accessible", () => {
    mockConnected.mockReturnValue(false);
    render(<MarketSummaryWidget />);
    expect(screen.getByLabelText("Refresh market summary")).toBeTruthy();
  });

  it("refresh button is present when disconnected", () => {
    mockConnected.mockReturnValue(false);
    render(<MarketSummaryWidget />);
    const btn = screen.getByLabelText("Refresh market summary") as HTMLButtonElement;
    expect(btn).toBeTruthy();
  });

  it("refresh button is enabled when connected", () => {
    mockConnected.mockReturnValue(true);
    render(<MarketSummaryWidget />);
    const btn = screen.getByLabelText("Refresh market summary") as HTMLButtonElement;
    expect(btn.disabled).toBe(false);
  });

  it("clicking refresh when connected does not throw", () => {
    mockConnected.mockReturnValue(true);
    render(<MarketSummaryWidget />);
    const btn = screen.getByLabelText("Refresh market summary");
    expect(() => fireEvent.click(btn)).not.toThrow();
  });

  it("breadth bar aria label is present", () => {
    mockConnected.mockReturnValue(false);
    render(<MarketSummaryWidget />);
    const bars = screen.getAllByLabelText(/Market breadth/i);
    expect(bars.length).toBeGreaterThan(0);
  });

  it("sector bars container has aria label", () => {
    mockConnected.mockReturnValue(false);
    render(<MarketSummaryWidget />);
    const sectors = screen.getByLabelText("Sector performance");
    expect(sectors).toBeTruthy();
  });
});
