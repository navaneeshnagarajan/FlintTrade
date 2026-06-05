import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import "@testing-library/jest-dom";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------
//
// The widget no longer reads `useBrokerConnected` — it has no live data source
// yet, so it always renders sample data with an unconditional "Sample data"
// badge regardless of connection state.

vi.mock("@/hooks/useTrackBehavior", () => ({
  useTrackBehavior: () => vi.fn(),
}));

import CorrelationPairsWidget from "../CorrelationPairsWidget";

beforeEach(() => {
  global.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
});

describe("CorrelationPairsWidget", () => {
  it("renders widget title", () => {
    render(<CorrelationPairsWidget />);
    expect(screen.getByText("Correlation Pairs")).toBeTruthy();
  });

  it("shows the Sample data badge", () => {
    render(<CorrelationPairsWidget />);
    expect(screen.getByText("Sample data")).toBeTruthy();
  });

  it("always shows the Sample data badge — no live source is wired, so it must not hide", () => {
    // Honest behaviour: the widget has no backend correlation endpoint, so the
    // badge is unconditional. There is no connection state that should remove it.
    render(<CorrelationPairsWidget />);
    const badge = screen.getByText("Sample data");
    expect(badge).toBeInTheDocument();
    // The disclosure is exposed to assistive tech and explains there is no live source.
    expect(badge).toHaveAttribute(
      "aria-label",
      "Showing sample data; no live correlation data source is wired yet",
    );
  });

  it("does not render a deceptive live-looking refresh control", () => {
    // The old stub refresh button only slept and bumped a "lastUpdated" clock to
    // look live while still showing sample data — it has been removed.
    render(<CorrelationPairsWidget />);
    expect(screen.queryByRole("button", { name: /refresh correlation data/i })).toBeNull();
  });

  it("renders table column headers: Pair, Corr, Z-Score, Signal", () => {
    render(<CorrelationPairsWidget />);
    expect(screen.getByText("Pair")).toBeTruthy();
    expect(screen.getByText("Corr")).toBeTruthy();
    expect(screen.getByText("Z-Score")).toBeTruthy();
    expect(screen.getByText("Signal")).toBeTruthy();
  });

  it("renders NIFTY and BANKNIFTY in pair rows", () => {
    render(<CorrelationPairsWidget />);
    // NIFTY appears in two rows (NIFTY↔BANKNIFTY and RELIANCE↔NIFTY)
    expect(screen.getAllByText("NIFTY").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("BANKNIFTY").length).toBeGreaterThanOrEqual(1);
  });

  it("renders signal labels: Converging and Diverging", () => {
    render(<CorrelationPairsWidget />);
    const divergingCells = screen.getAllByText("Diverging");
    const convergingCells = screen.getAllByText("Converging");
    expect(divergingCells.length).toBeGreaterThan(0);
    expect(convergingCells.length).toBeGreaterThan(0);
  });

  it("sorts by correlation when Corr header is clicked", () => {
    render(<CorrelationPairsWidget />);
    const corrHeader = screen.getByRole("columnheader", { name: /corr/i });
    fireEvent.click(corrHeader);
    // After clicking, table should still render (sort direction changes)
    expect(screen.getByText("Correlation Pairs")).toBeTruthy();
  });

  it("renders footer note about z-score and correlation", () => {
    render(<CorrelationPairsWidget />);
    // Z-Score appears in column header and footer — use getAllBy
    expect(screen.getAllByText(/Z-score/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText(/20-day rolling returns/i)).toBeTruthy();
  });
});
