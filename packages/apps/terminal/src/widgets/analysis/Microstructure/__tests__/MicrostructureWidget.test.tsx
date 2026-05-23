import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, act } from "@testing-library/react";
import "@testing-library/jest-dom";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

vi.mock("@/hooks/useTrackBehavior", () => ({
  useTrackBehavior: () => vi.fn(),
}));

vi.mock("@/hooks/useBrokerConnected", () => ({
  useBrokerConnected: () => false,
}));

import MicrostructureWidget from "../MicrostructureWidget";

describe("MicrostructureWidget", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("renders widget header with title", () => {
    render(<MicrostructureWidget />);
    expect(screen.getByText("Market Microstructure")).toBeTruthy();
  });

  it("shows Sample badge when not connected", () => {
    render(<MicrostructureWidget />);
    expect(screen.getByText("Sample")).toBeTruthy();
  });

  it("renders tick velocity section", () => {
    render(<MicrostructureWidget />);
    expect(screen.getAllByText(/Tick Velocity/i).length).toBeGreaterThan(0);
  });

  it("renders bid ask imbalance section", () => {
    render(<MicrostructureWidget />);
    expect(screen.getByText(/Bid \/ Ask Imbalance/i)).toBeTruthy();
  });

  it("renders trade direction section", () => {
    render(<MicrostructureWidget />);
    expect(screen.getByText(/Trade Direction/i)).toBeTruthy();
  });

  it("renders large orders stat", () => {
    render(<MicrostructureWidget />);
    expect(screen.getByText("Large Orders (60s)")).toBeTruthy();
  });

  it("renders sparkline with correct aria label", () => {
    render(<MicrostructureWidget />);
    expect(screen.getByLabelText(/tick velocity sparkline/i)).toBeTruthy();
  });

  it("renders imbalance bar with aria label", () => {
    render(<MicrostructureWidget />);
    expect(screen.getByLabelText(/bid ask imbalance/i)).toBeTruthy();
  });

  it("updates stats after timer tick", () => {
    render(<MicrostructureWidget />);
    act(() => {
      vi.advanceTimersByTime(1000);
    });
    // widget still renders without error after update
    expect(screen.getByText("Market Microstructure")).toBeTruthy();
  });

  it("has correct aria label on widget container", () => {
    render(<MicrostructureWidget />);
    expect(screen.getByLabelText("Market Microstructure widget")).toBeTruthy();
  });
});
