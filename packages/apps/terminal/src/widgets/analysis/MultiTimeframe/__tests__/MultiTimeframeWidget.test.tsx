import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
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
import MultiTimeframeWidget from "../MultiTimeframeWidget";

const mockConnected = useBrokerConnected as ReturnType<typeof vi.fn>;

beforeEach(() => {
  global.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
});

describe("MultiTimeframeWidget", () => {
  it("renders widget title", () => {
    mockConnected.mockReturnValue(false);
    render(<MultiTimeframeWidget />);
    expect(screen.getByText("Multi-Timeframe")).toBeTruthy();
  });

  it("shows the Sample data badge when broker disconnected", () => {
    mockConnected.mockReturnValue(false);
    render(<MultiTimeframeWidget />);
    expect(screen.getByText("Sample data")).toBeTruthy();
  });

  // The widget has no live multi-timeframe endpoint wired yet, so it always
  // renders sample signals. The badge must therefore stay visible even when a
  // broker is connected — hiding it would mislead a live user into trusting
  // fabricated data. This is the honest-disclosure guarantee.
  it("still shows the Sample data badge when broker connected", () => {
    mockConnected.mockReturnValue(true);
    render(<MultiTimeframeWidget />);
    expect(screen.getByText("Sample data")).toBeTruthy();
  });

  it("badge discloses that no live source is wired via its accessible name", () => {
    mockConnected.mockReturnValue(true);
    render(<MultiTimeframeWidget />);
    const badge = screen.getByText("Sample data");
    expect(badge.getAttribute("aria-label")).toMatch(/no live multi-timeframe source/i);
  });

  it("renders all four timeframe rows", () => {
    mockConnected.mockReturnValue(false);
    render(<MultiTimeframeWidget />);
    expect(screen.getByText("5m")).toBeTruthy();
    expect(screen.getByText("15m")).toBeTruthy();
    expect(screen.getByText("1h")).toBeTruthy();
    expect(screen.getByText("1D")).toBeTruthy();
  });

  it("renders column headers: TF, Trend, RSI, MACD, EMA", () => {
    mockConnected.mockReturnValue(false);
    render(<MultiTimeframeWidget />);
    expect(screen.getByText("TF")).toBeTruthy();
    expect(screen.getByText("Trend")).toBeTruthy();
    expect(screen.getByText("RSI")).toBeTruthy();
    expect(screen.getByText("MACD")).toBeTruthy();
    expect(screen.getByText("EMA")).toBeTruthy();
  });

  it("renders confluence section", () => {
    mockConnected.mockReturnValue(false);
    render(<MultiTimeframeWidget />);
    expect(screen.getByText("Confluence")).toBeTruthy();
  });

  it("renders symbol selector defaulting to NIFTY", () => {
    mockConnected.mockReturnValue(false);
    render(<MultiTimeframeWidget />);
    expect(screen.getByRole("button", { name: /selected symbol: NIFTY/i })).toBeTruthy();
  });

  it("opens symbol dropdown and shows alternative symbols", () => {
    mockConnected.mockReturnValue(false);
    render(<MultiTimeframeWidget />);
    fireEvent.click(screen.getByRole("button", { name: /selected symbol/i }));
    expect(screen.getByText("BANKNIFTY")).toBeTruthy();
    expect(screen.getByText("RELIANCE")).toBeTruthy();
  });

  it("switches symbol when dropdown option is selected", () => {
    mockConnected.mockReturnValue(false);
    render(<MultiTimeframeWidget />);
    fireEvent.click(screen.getByRole("button", { name: /selected symbol/i }));
    fireEvent.click(screen.getByText("BANKNIFTY"));
    expect(screen.getByRole("button", { name: /selected symbol: BANKNIFTY/i })).toBeTruthy();
  });

  it("renders legend section", () => {
    mockConnected.mockReturnValue(false);
    render(<MultiTimeframeWidget />);
    expect(screen.getByText("Legend")).toBeTruthy();
    expect(screen.getByText(/Overbought/i)).toBeTruthy();
    expect(screen.getByText(/Oversold/i)).toBeTruthy();
  });
});
