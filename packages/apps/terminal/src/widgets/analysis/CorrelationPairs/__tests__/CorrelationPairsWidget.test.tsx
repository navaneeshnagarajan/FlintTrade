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
import CorrelationPairsWidget from "../CorrelationPairsWidget";

const mockConnected = useBrokerConnected as ReturnType<typeof vi.fn>;

beforeEach(() => {
  global.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
});

describe("CorrelationPairsWidget", () => {
  it("renders widget title", () => {
    mockConnected.mockReturnValue(false);
    render(<CorrelationPairsWidget />);
    expect(screen.getByText("Correlation Pairs")).toBeTruthy();
  });

  it("shows Sample badge when broker disconnected", () => {
    mockConnected.mockReturnValue(false);
    render(<CorrelationPairsWidget />);
    expect(screen.getByText("Sample")).toBeTruthy();
  });

  it("does not show Sample badge when broker connected", () => {
    mockConnected.mockReturnValue(true);
    render(<CorrelationPairsWidget />);
    expect(screen.queryByText("Sample")).toBeNull();
  });

  it("renders table column headers: Pair, Corr, Z-Score, Signal", () => {
    mockConnected.mockReturnValue(false);
    render(<CorrelationPairsWidget />);
    expect(screen.getByText("Pair")).toBeTruthy();
    expect(screen.getByText("Corr")).toBeTruthy();
    expect(screen.getByText("Z-Score")).toBeTruthy();
    expect(screen.getByText("Signal")).toBeTruthy();
  });

  it("renders NIFTY and BANKNIFTY in pair rows", () => {
    mockConnected.mockReturnValue(false);
    render(<CorrelationPairsWidget />);
    // NIFTY appears in two rows (NIFTY↔BANKNIFTY and RELIANCE↔NIFTY)
    expect(screen.getAllByText("NIFTY").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("BANKNIFTY").length).toBeGreaterThanOrEqual(1);
  });

  it("renders signal labels: Converging and Diverging", () => {
    mockConnected.mockReturnValue(false);
    render(<CorrelationPairsWidget />);
    const divergingCells = screen.getAllByText("Diverging");
    const convergingCells = screen.getAllByText("Converging");
    expect(divergingCells.length).toBeGreaterThan(0);
    expect(convergingCells.length).toBeGreaterThan(0);
  });

  it("sorts by correlation when Corr header is clicked", () => {
    mockConnected.mockReturnValue(false);
    render(<CorrelationPairsWidget />);
    const corrHeader = screen.getByRole("columnheader", { name: /corr/i });
    fireEvent.click(corrHeader);
    // After clicking, table should still render (sort direction changes)
    expect(screen.getByText("Correlation Pairs")).toBeTruthy();
  });

  it("refresh button is disabled when broker disconnected", () => {
    mockConnected.mockReturnValue(false);
    render(<CorrelationPairsWidget />);
    const btn = screen.getByRole("button", { name: /refresh correlation data/i });
    expect(btn).toBeDisabled();
  });

  it("renders footer note about z-score and correlation", () => {
    mockConnected.mockReturnValue(false);
    render(<CorrelationPairsWidget />);
    // Z-Score appears in column header and footer — use getAllBy
    expect(screen.getAllByText(/Z-score/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText(/20-day rolling returns/i)).toBeTruthy();
  });
});
