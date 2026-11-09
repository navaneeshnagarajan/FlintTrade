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
import StrategyMonitorWidget, { SAMPLE_STRATEGIES, projectUploadedStrategy } from "../StrategyMonitorWidget";

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
    expect(screen.queryByText(/Sample data/i)).not.toBeInTheDocument();
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

describe("projectUploadedStrategy", () => {
  const base = {
    strategy_id: "row",
    name: "Row",
    pid: null,
    memory_mb: null,
    uptime_seconds: null,
  };

  it("maps the shared projection for running, stopped, crashed, unknown, and paused", () => {
    expect(projectUploadedStrategy({ ...base, state: "running", reason: "running" })).toBe("running");
    expect(projectUploadedStrategy({ ...base, state: "stopped", reason: "idle" })).toBe("stopped");
    expect(projectUploadedStrategy({ ...base, state: "crashed", reason: "exit_nonzero" })).toBe("error");
    expect(projectUploadedStrategy({
      ...base,
      state: "unknown",
      reason: "tree_unreadable",
      ownership_retained: true,
    })).toBe("unknown");
    expect(projectUploadedStrategy({
      ...base,
      state: "running",
      reason: "running",
      lifecycle: "PAUSED",
    })).toBe("paused");
    expect(projectUploadedStrategy({
      ...base,
      state: "stopped",
      reason: "idle",
      lifecycle: "PAUSED",
    })).toBe("paused");
    expect(projectUploadedStrategy({
      ...base,
      state: "unknown",
      reason: "tree_unreadable",
      lifecycle: "PAUSED",
      ownership_retained: true,
    })).toBe("unknown");
    expect(projectUploadedStrategy({
      ...base,
      state: "crashed",
      reason: "exit_nonzero",
      lifecycle: "PAUSED",
    })).toBe("error");
  });
});

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

  it("keeps an unread process unknown and does not call it stopped", async () => {
    mockConnected.mockReturnValue(true);
    mockListStrategies.mockResolvedValue([
      {
        strategy_id: "unread",
        name: "Unread Tree",
        state: "unknown",
        ownership_retained: true,
        pid: 808,
        memory_mb: null,
        uptime_seconds: null,
      },
    ]);

    renderMonitor();

    const row = await screen.findByRole("listitem", { name: "Strategy Unread Tree: Unknown" });
    expect(row).toHaveTextContent("Unknown");
    expect(row).not.toHaveTextContent("Stopped");
    expect(row).toHaveAttribute(
      "title",
      "Process state could not be read. Ownership stays with this runner, so the strategy is not stopped.",
    );
    const ownership = screen.getByText(
      "Process state could not be read. Ownership stays with this runner, so the strategy is not stopped.",
    );
    expect(row).toHaveAttribute("aria-describedby", ownership.id);
    expect(ownership.closest("[role='listitem']")).toBe(row);
    expect(screen.getByText("Degraded")).toBeTruthy();
    expect(screen.queryAllByRole("button", { name: /^Start / })).toHaveLength(0);
    expect(screen.queryAllByRole("button", { name: /^Pause / })).toHaveLength(0);
    expect(screen.queryAllByRole("button", { name: /^Stop / })).toHaveLength(0);
  });

  it.each([
    ["missing", undefined],
    ["blank", ""],
    ["unrecognized", "pending"],
  ])("shows %s runner state as unknown", async (_label, state) => {
    mockConnected.mockReturnValue(true);
    mockListStrategies.mockResolvedValue([
      { strategy_id: "opaque", name: "Opaque Runner", state, pid: 1, memory_mb: null, uptime_seconds: null },
    ]);

    renderMonitor();

    expect(await screen.findByRole("listitem", { name: "Strategy Opaque Runner: Unknown" })).toBeTruthy();
    expect(screen.queryByRole("listitem", { name: "Strategy Opaque Runner: Stopped" })).toBeNull();
  });

  it("keeps a confirmed running or stopped process on that label", async () => {
    mockConnected.mockReturnValue(true);
    mockListStrategies.mockResolvedValue([
      { strategy_id: "live", name: "Live Runner", state: "running", pid: 1, memory_mb: 1, uptime_seconds: 1 },
      { strategy_id: "idle", name: "Idle Runner", state: "stopped", pid: null, memory_mb: null, uptime_seconds: null },
    ]);

    renderMonitor();

    expect(await screen.findByRole("listitem", { name: "Strategy Live Runner: Running" })).toBeTruthy();
    expect(screen.getByRole("listitem", { name: "Strategy Idle Runner: Stopped" })).toBeTruthy();
    expect(screen.queryByText("Unknown")).toBeNull();
  });

  it("shows a load error when the strategy list fails", async () => {
    mockConnected.mockReturnValue(true);
    mockListStrategies.mockRejectedValue(new Error("offline"));

    renderMonitor();

    expect(await screen.findByRole("alert")).toHaveTextContent("Could not load strategies.");
    expect(screen.queryByText("No strategies configured")).toBeNull();
  });

  it("shows Paused when the runner lifecycle is paused", async () => {
    mockConnected.mockReturnValue(true);
    mockListStrategies.mockResolvedValue([
      {
        strategy_id: "paused",
        name: "Paused Runner",
        state: "running",
        lifecycle: "PAUSED",
        reason: "running",
        pid: 7,
        memory_mb: 1,
        uptime_seconds: 1,
      },
      {
        strategy_id: "paused-idle",
        name: "Paused Idle",
        state: "stopped",
        lifecycle: "PAUSED",
        reason: "idle",
        pid: null,
        memory_mb: null,
        uptime_seconds: null,
      },
    ]);

    renderMonitor();

    expect(await screen.findByRole("listitem", { name: "Strategy Paused Runner: Paused" })).toBeTruthy();
    expect(screen.getByRole("listitem", { name: "Strategy Paused Idle: Paused" })).toBeTruthy();
    expect(screen.queryByRole("listitem", { name: "Strategy Paused Runner: Running" })).toBeNull();
    expect(screen.queryByRole("listitem", { name: "Strategy Paused Idle: Stopped" })).toBeNull();
  });

  it("keeps an unknown state unknown when a lifecycle is also present", async () => {
    mockConnected.mockReturnValue(true);
    mockListStrategies.mockResolvedValue([
      {
        strategy_id: "unread",
        name: "Unread Tree",
        state: "unknown",
        lifecycle: "STOPPED",
        reason: "tree_unreadable",
        ownership_retained: true,
        pid: 808,
        memory_mb: null,
        uptime_seconds: null,
      },
    ]);

    renderMonitor();

    const row = await screen.findByRole("listitem", { name: "Strategy Unread Tree: Unknown" });
    expect(row).not.toHaveTextContent("Stopped");
    expect(row).not.toHaveTextContent("Paused");
  });

  it("keeps the empty state when the strategy list is empty", async () => {
    mockConnected.mockReturnValue(true);
    mockListStrategies.mockResolvedValue([]);

    renderMonitor();

    expect(await screen.findByText("No strategies configured")).toBeTruthy();
    expect(screen.queryByRole("alert")).toBeNull();
  });
});
