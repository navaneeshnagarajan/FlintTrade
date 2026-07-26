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

const mockListStrategies = vi.hoisted(() =>
  vi.fn((): Promise<unknown[]> => Promise.resolve([])),
);
vi.mock("@/services/ftApi.backtest", () => ({
  listUploadedStrategies: mockListStrategies,
}));

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useBrokerConnected } from "@/hooks/useBrokerConnected";
import StrategyMonitorWidget, { SAMPLE_STRATEGIES } from "../StrategyMonitorWidget";

/** The widget now reads real uploaded strategies, so it needs a query client. */
function renderMonitor() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <StrategyMonitorWidget />
    </QueryClientProvider>,
  );
}

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
    renderMonitor();
    expect(screen.getByText("Strategy Monitor")).toBeTruthy();
  });

  it("labels the surface as a local preview even when connected", () => {
    mockConnected.mockReturnValue(true);
    renderMonitor();
    expect(screen.getByText("Local preview")).toBeTruthy();
  });

  it("shows the 'Sample data' badge when disconnected", () => {
    mockConnected.mockReturnValue(false);
    renderMonitor();
    const badge = screen.getByText("Sample data");
    expect(badge).toBeTruthy();
    expect(badge.getAttribute("role")).toBe("status");
  });

  it("does not show the sample badge when connected (shows empty state instead)", () => {
    mockConnected.mockReturnValue(true);
    renderMonitor();
    expect(screen.queryByText("Sample data")).toBeNull();
  });

  it("does NOT render fabricated sample strategies when a broker is connected", () => {
    // House rule: no mock/live-looking P&L when connected. Must show the honest
    // empty state instead of SAMPLE_STRATEGIES.
    mockConnected.mockReturnValue(true);
    renderMonitor();
    for (const s of SAMPLE_STRATEGIES) {
      expect(screen.queryByText(s.name)).toBeNull();
    }
    expect(screen.getByText("No strategies configured")).toBeTruthy();
  });

  it("offers a Strategy Lab action from the empty state", () => {
    mockConnected.mockReturnValue(true);
    renderMonitor();
    const listener = vi.fn();
    window.addEventListener("flinttrade:navigate", listener);
    fireEvent.click(screen.getByRole("button", { name: /open strategy lab/i }));
    expect(listener).toHaveBeenCalledTimes(1);
    expect((listener.mock.calls[0][0] as CustomEvent).detail).toBe("/lab");
    window.removeEventListener("flinttrade:navigate", listener);
  });

  it("renders all strategy names", () => {
    mockConnected.mockReturnValue(false);
    renderMonitor();
    for (const s of SAMPLE_STRATEGIES) {
      expect(screen.getByText(s.name)).toBeTruthy();
    }
  });

  it("renders strategy list with correct aria-label", () => {
    mockConnected.mockReturnValue(false);
    renderMonitor();
    expect(screen.getByRole("list", { name: /strategy list/i })).toBeTruthy();
  });

  it("renders running count in header", () => {
    mockConnected.mockReturnValue(false);
    renderMonitor();
    expect(screen.getByText(/running/)).toBeTruthy();
  });

  it("renders health badge (All OK, Degraded, or Critical)", () => {
    mockConnected.mockReturnValue(false);
    renderMonitor();
    const health = screen.queryByText("All OK") ?? screen.queryByText("Degraded") ?? screen.queryByText("Critical");
    expect(health).toBeTruthy();
  });

  it("error strategy shows Critical health", () => {
    mockConnected.mockReturnValue(false);
    renderMonitor();
    // SAMPLE_STRATEGIES has one error strategy → Critical
    expect(screen.getByText("Critical")).toBeTruthy();
  });

  it("clicking expand shows strategy logs", () => {
    mockConnected.mockReturnValue(false);
    renderMonitor();
    // click expand on first strategy row
    const expandButtons = screen.getAllByRole("button", { name: /expand logs/i });
    expect(expandButtons.length).toBeGreaterThan(0);
    fireEvent.click(expandButtons[0]);
    // after expand, a log message from sample data should appear
    const firstStrategy = SAMPLE_STRATEGIES[0];
    expect(screen.getByText(firstStrategy.logs[0].message)).toBeTruthy();
  });

  it("does not expose lifecycle controls without a backend mutation", () => {
    mockConnected.mockReturnValue(false);
    renderMonitor();
    expect(screen.queryAllByRole("button", { name: /^Start / })).toHaveLength(0);
    expect(screen.queryAllByRole("button", { name: /^Pause / })).toHaveLength(0);
    expect(screen.queryAllByRole("button", { name: /^Stop / })).toHaveLength(0);
    expect(screen.queryByText("Actions")).toBeNull();
  });

  it("renders footer with total P&L, trades, signals", () => {
    mockConnected.mockReturnValue(false);
    renderMonitor();
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

describe("StrategyMonitorWidget — real uploaded strategies", () => {
  it("renders the strategies the engine reports instead of a permanently empty list", async () => {
    // Connected used to mean `[]` unconditionally, because nothing called
    // GET /api/v1/strategies. An operator with a strategy running saw nothing,
    // indistinguishable from having uploaded none.
    mockConnected.mockReturnValue(true);
    mockListStrategies.mockResolvedValue([
      { strategy_id: "ema_cross", name: "EMA Crossover", state: "running",
        pid: 4242, memory_mb: 38.5, uptime_seconds: 900 },
      { strategy_id: "broken", name: "Broken Strategy", state: "crashed",
        pid: null, memory_mb: null, uptime_seconds: null },
    ]);

    renderMonitor();

    expect(await screen.findByText("EMA Crossover")).toBeTruthy();
    expect(screen.getByText("Broken Strategy")).toBeTruthy();
    // A crashed process reads as an error row, not as merely stopped.
    expect(screen.getAllByText(/error/i).length).toBeGreaterThan(0);
  });

  it("does not call the engine while disconnected", () => {
    mockConnected.mockReturnValue(false);
    mockListStrategies.mockClear();
    renderMonitor();
    expect(mockListStrategies).not.toHaveBeenCalled();
  });
});
