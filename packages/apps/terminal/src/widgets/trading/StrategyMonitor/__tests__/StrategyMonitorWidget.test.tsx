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
import StrategyMonitorWidget, { SAMPLE_STRATEGIES } from "../StrategyMonitorWidget";

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

describe("StrategyMonitorWidget", () => {
  it("renders widget title", () => {
    mockConnected.mockReturnValue(false);
    render(<StrategyMonitorWidget />);
    expect(screen.getByText("Strategy Monitor")).toBeTruthy();
  });

  it("shows the 'Sample data' badge when disconnected", () => {
    mockConnected.mockReturnValue(false);
    render(<StrategyMonitorWidget />);
    const badge = screen.getByText("Sample data");
    expect(badge).toBeTruthy();
    expect(badge.getAttribute("role")).toBe("status");
  });

  it("does not show the sample badge when connected (shows empty state instead)", () => {
    mockConnected.mockReturnValue(true);
    render(<StrategyMonitorWidget />);
    expect(screen.queryByText("Sample data")).toBeNull();
  });

  it("does NOT render fabricated sample strategies when a broker is connected", () => {
    // House rule: no mock/live-looking P&L when connected. Must show the honest
    // empty state instead of SAMPLE_STRATEGIES.
    mockConnected.mockReturnValue(true);
    render(<StrategyMonitorWidget />);
    for (const s of SAMPLE_STRATEGIES) {
      expect(screen.queryByText(s.name)).toBeNull();
    }
    expect(screen.getByText("No strategies configured")).toBeTruthy();
  });

  it("offers a Strategy Lab action from the empty state", () => {
    mockConnected.mockReturnValue(true);
    render(<StrategyMonitorWidget />);
    const listener = vi.fn();
    window.addEventListener("flinttrade:navigate", listener);
    fireEvent.click(screen.getByRole("button", { name: /open strategy lab/i }));
    expect(listener).toHaveBeenCalledTimes(1);
    expect((listener.mock.calls[0][0] as CustomEvent).detail).toBe("/lab");
    window.removeEventListener("flinttrade:navigate", listener);
  });

  it("renders all strategy names", () => {
    mockConnected.mockReturnValue(false);
    render(<StrategyMonitorWidget />);
    for (const s of SAMPLE_STRATEGIES) {
      expect(screen.getByText(s.name)).toBeTruthy();
    }
  });

  it("renders strategy list with correct aria-label", () => {
    mockConnected.mockReturnValue(false);
    render(<StrategyMonitorWidget />);
    expect(screen.getByRole("list", { name: /strategy list/i })).toBeTruthy();
  });

  it("renders running count in header", () => {
    mockConnected.mockReturnValue(false);
    render(<StrategyMonitorWidget />);
    expect(screen.getByText(/running/)).toBeTruthy();
  });

  it("renders health badge (All OK, Degraded, or Critical)", () => {
    mockConnected.mockReturnValue(false);
    render(<StrategyMonitorWidget />);
    const health = screen.queryByText("All OK") ?? screen.queryByText("Degraded") ?? screen.queryByText("Critical");
    expect(health).toBeTruthy();
  });

  it("error strategy shows Critical health", () => {
    mockConnected.mockReturnValue(false);
    render(<StrategyMonitorWidget />);
    // SAMPLE_STRATEGIES has one error strategy → Critical
    expect(screen.getByText("Critical")).toBeTruthy();
  });

  it("clicking expand shows strategy logs", () => {
    mockConnected.mockReturnValue(false);
    render(<StrategyMonitorWidget />);
    // click expand on first strategy row
    const expandButtons = screen.getAllByRole("button", { name: /expand logs/i });
    expect(expandButtons.length).toBeGreaterThan(0);
    fireEvent.click(expandButtons[0]);
    // after expand, a log message from sample data should appear
    const firstStrategy = SAMPLE_STRATEGIES[0];
    expect(screen.getByText(firstStrategy.logs[0].message)).toBeTruthy();
  });

  it("Start button is disabled for running strategy", () => {
    mockConnected.mockReturnValue(false);
    render(<StrategyMonitorWidget />);
    const runningStrategy = SAMPLE_STRATEGIES.find((s) => s.status === "running")!;
    const startBtn = screen.getByLabelText(`Start ${runningStrategy.name}`);
    expect(startBtn).toBeTruthy();
    expect((startBtn as HTMLButtonElement).disabled).toBe(true);
  });

  it("renders footer with total P&L, trades, signals", () => {
    mockConnected.mockReturnValue(false);
    render(<StrategyMonitorWidget />);
    expect(screen.getByText(/Total P&L/i)).toBeTruthy();
    expect(screen.getByText(/Trades/i)).toBeTruthy();
    expect(screen.getByText(/Signals/i)).toBeTruthy();
  });
});

// ---------------------------------------------------------------------------
// Sample data tests
// ---------------------------------------------------------------------------

describe("SAMPLE_STRATEGIES", () => {
  it("has 4 strategies", () => {
    expect(SAMPLE_STRATEGIES).toHaveLength(4);
  });

  it("includes one error status strategy", () => {
    const errorStrats = SAMPLE_STRATEGIES.filter((s) => s.status === "error");
    expect(errorStrats.length).toBeGreaterThanOrEqual(1);
  });

  it("each strategy has exactly 5 log entries", () => {
    for (const s of SAMPLE_STRATEGIES) {
      expect(s.logs).toHaveLength(5);
    }
  });

  it("all strategies have unique ids", () => {
    const ids = SAMPLE_STRATEGIES.map((s) => s.id);
    expect(new Set(ids).size).toBe(ids.length);
  });

  it("running strategies have non-negative trades count", () => {
    for (const s of SAMPLE_STRATEGIES.filter((s) => s.status === "running")) {
      expect(s.tradesToday).toBeGreaterThanOrEqual(0);
    }
  });
});
