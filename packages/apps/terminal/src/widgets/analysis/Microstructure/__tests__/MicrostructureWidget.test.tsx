import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, act } from "@testing-library/react";
import "@testing-library/jest-dom";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

vi.mock("@/hooks/useTrackBehavior", () => ({
  useTrackBehavior: () => vi.fn(),
}));

// NOTE: the widget no longer reads `useBrokerConnected` — the "Sample data"
// badge is now unconditional because no live tick feed is wired in yet. We
// still mock the hook defensively in case any transitive import touches it.
vi.mock("@/hooks/useBrokerConnected", () => ({
  useBrokerConnected: () => true,
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

  it("always shows the 'Sample data' badge — even when a broker is connected", () => {
    // The widget has no live tick feed wired yet, so it must honestly disclose
    // that it is rendering sample data regardless of connection state. The
    // mocked `useBrokerConnected` returns true here, proving the badge is not
    // gated on disconnect.
    render(<MicrostructureWidget />);
    expect(screen.getByText("Sample data")).toBeTruthy();
  });

  it("exposes the sample badge as a status with an honest accessible label", () => {
    render(<MicrostructureWidget />);
    const badge = screen.getByRole("status", {
      name: /showing sample data; no live tick feed wired yet/i,
    });
    expect(badge).toBeTruthy();
    expect(badge).toHaveTextContent("Sample data");
  });

  it("does not render a deceptive 'Live updating' affordance", () => {
    // The old spinning RefreshCw indicator implied a live data source; it must
    // be gone so nothing suggests the animated sample ticks are real.
    render(<MicrostructureWidget />);
    expect(screen.queryByLabelText(/live updating/i)).toBeNull();
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
    const sparkline = screen.getByRole("img", { name: /tick velocity sparkline/i });

    expect(sparkline).toHaveAttribute("viewBox", "0 0 160 42");
    expect(sparkline.querySelector("polyline")).not.toBeInTheDocument();
    expect(sparkline.querySelectorAll("path").length).toBeGreaterThan(0);
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
