import { describe, it, expect, vi, beforeAll } from "vitest";
import { render, screen } from "@testing-library/react";

// ---------------------------------------------------------------------------
// Mocks
//
// The widget no longer reads `useBrokerConnected` — every section renders from
// the SAMPLE_* constants regardless of connection state, and the "Sample data"
// badge is shown unconditionally. We still mock the hook so the module graph
// resolves cleanly even though the widget does not consume it any more.
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

  it("shows the 'Sample data' badge when disconnected", () => {
    mockConnected.mockReturnValue(false);
    render(<MarketSummaryWidget />);
    expect(screen.getByText("Sample data")).toBeTruthy();
  });

  it("STILL shows the 'Sample data' badge when connected (no live source is wired yet)", () => {
    // Honesty regression guard: the badge previously hid behind `!isConnected`,
    // so a connected user saw fabricated indices/breadth/FII-DII with nothing
    // marking them as sample. The badge must now be unconditional.
    mockConnected.mockReturnValue(true);
    render(<MarketSummaryWidget />);
    expect(screen.getByText("Sample data")).toBeTruthy();
  });

  it("badge carries an honest status role and disclosure label", () => {
    mockConnected.mockReturnValue(true);
    render(<MarketSummaryWidget />);
    const badge = screen.getByRole("status", {
      name: /no live market-overview source is wired yet/i,
    });
    expect(badge.textContent).toContain("Sample data");
  });

  it("renders no live-looking refresh control or timestamp (nothing implies live data)", () => {
    // The old stub had a "Refresh market summary" button + a spinning loader and
    // a clock that only updated `lastUpdate`, making sample data look live.
    mockConnected.mockReturnValue(true);
    render(<MarketSummaryWidget />);
    expect(screen.queryByLabelText("Refresh market summary")).toBeNull();
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
