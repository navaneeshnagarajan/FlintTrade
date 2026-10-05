/**
 * AgentPanel.test — autonomous-agent control plane (start/stop/status).
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";
import "@testing-library/jest-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

let mockMode = "live";
vi.mock("@/stores/modeStore", () => ({
  useModeStore: (selector?: (s: { mode: string }) => unknown) =>
    typeof selector === "function" ? selector({ mode: mockMode }) : { mode: mockMode },
}));
vi.mock("@/services/ftApi", () => ({
  getAgentStatus: vi.fn(),
  startAgent: vi.fn(),
  stopAgent: vi.fn(),
  getPracticeAgentRuns: vi.fn(),
  getPracticeAgentEvents: vi.fn(),
  resolvePracticeAgentRun: vi.fn(),
}));
vi.mock("@/components/ui/GlassCard", () => ({
  GlassCard: ({ children, ...props }: Record<string, unknown>) => (
    <div {...props}>{children as React.ReactNode}</div>
  ),
}));

import AgentPanel from "../AgentPanel";
import { getAgentStatus, startAgent, stopAgent, getPracticeAgentRuns, getPracticeAgentEvents, resolvePracticeAgentRun } from "@/services/ftApi";

const IDLE = {
  enabled: true,
  running: false,
  started_at: "",
  params: {},
  actor_id: "autonomous-trader",
};

const RUNNING = {
  ...IDLE,
  running: true,
  agent_status: "running",
  daily_pnl: -125.0,
  cycle_count: 7,
  params: { symbols: ["RELIANCE"] },
  position_details: {
    RELIANCE: {
      entry_price: 2500.0,
      stop_loss: 2450.0,
      take_profit: 2600.0,
      action: "BUY",
      quantity: 1,
    },
  },
};

function renderPanel(qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })) {
  const result = render(
    <QueryClientProvider client={qc}>
      <AgentPanel />
    </QueryClientProvider>,
  );
  return { ...result, rerenderMode: () => result.rerender(<QueryClientProvider client={qc}><AgentPanel /></QueryClientProvider>) };
}

describe("AgentPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockMode = "live";
    vi.mocked(getPracticeAgentRuns).mockResolvedValue([]);
    vi.mocked(getPracticeAgentEvents).mockResolvedValue([]);
  });

  it("shows the disabled hint with the exact enablement keys", async () => {
    vi.mocked(getAgentStatus).mockResolvedValue({ ...IDLE, enabled: false });
    renderPanel();

    await waitFor(() =>
      expect(screen.getByText("ai.autonomous_agent.enabled")).toBeInTheDocument(),
    );
    expect(screen.getByText("brokers.account_acls")).toBeInTheDocument();
  });

  it("starts a session with the parsed form values", async () => {
    vi.mocked(getAgentStatus).mockResolvedValue(IDLE);
    vi.mocked(startAgent).mockResolvedValue(RUNNING);
    renderPanel();

    await waitFor(() => expect(screen.getByText("Idle")).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText("Agent symbols"), {
      target: { value: "reliance, icicibank" },
    });
    fireEvent.click(screen.getByRole("button", { name: /start agent/i }));

    await waitFor(() => expect(startAgent).toHaveBeenCalledOnce());
    expect(vi.mocked(startAgent).mock.calls[0][0]).toEqual({
      symbols: ["RELIANCE", "ICICIBANK"],
      exchange: "NSE",
      max_position_size: 1,
      stop_loss_pct: 2,
      take_profit_pct: 4,
    });
  });

  it("surfaces the backend's refusal verbatim (e.g. the ACL instruction)", async () => {
    vi.mocked(getAgentStatus).mockResolvedValue(IDLE);
    vi.mocked(startAgent).mockRejectedValue(
      new Error(
        "The agent actor 'autonomous-trader' is not authorised for openalgo:default. "
        + "Add it to workspace.json brokers.account_acls['openalgo']['default'] to grant access.",
      ),
    );
    renderPanel();

    await waitFor(() => expect(screen.getByText("Idle")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /start agent/i }));

    await waitFor(() =>
      expect(screen.getByText(/not authorised for openalgo:default/)).toBeInTheDocument(),
    );
  });

  it("renders the live session and stops with square-off", async () => {
    vi.mocked(getAgentStatus).mockResolvedValue(RUNNING);
    vi.mocked(stopAgent).mockResolvedValue({ ...RUNNING, running: false });
    renderPanel();

    await waitFor(() => expect(screen.getByText("Running")).toBeInTheDocument());
    // RELIANCE appears in the session summary AND the positions table.
    expect(screen.getAllByText("RELIANCE").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByRole("table", { name: "Agent positions" })).toBeInTheDocument();
    expect(screen.getByText("2450.00")).toBeInTheDocument(); // SL column

    fireEvent.click(screen.getByRole("button", { name: /stop & square off/i }));
    await waitFor(() => expect(stopAgent).toHaveBeenCalledOnce());
  });

  it("blocks starting in Explore with an honest hint", async () => {
    mockMode = "explore";
    vi.mocked(getAgentStatus).mockResolvedValue(IDLE);
    renderPanel();

    await waitFor(() =>
      expect(screen.getByText(/switch to Practice or Live/i)).toBeInTheDocument(),
    );
    expect(screen.getByRole("button", { name: /start agent/i })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: /start agent/i }));
    expect(startAgent).not.toHaveBeenCalled();
  });
});


const PRACTICE_RUN = {
  run_id: "practice-one",
  mode: "practice" as const,
  status: "stopped",
  config: { symbols: ["RELIANCE"] },
  snapshot: { ...IDLE, mode: "practice" as const, agent_status: "stopped" },
  error: null,
  created_at: "2026-09-30T09:00:00Z",
  updated_at: "2026-09-30T09:30:00Z",
};

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: Error) => void;
  const promise = new Promise<T>((res, rej) => { resolve = res; reject = rej; });
  return { promise, resolve, reject };
}

describe("AgentPanel Practice harness", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockMode = "practice";
    vi.mocked(getAgentStatus).mockResolvedValue({ ...IDLE, mode: "practice" });
    vi.mocked(getPracticeAgentRuns).mockResolvedValue([]);
    vi.mocked(getPracticeAgentEvents).mockResolvedValue([]);
  });

  it("starts a simulated-money Practice session with quantities labelled as units", async () => {
    vi.mocked(startAgent).mockResolvedValue({ ...RUNNING, mode: "practice" });
    renderPanel();
    await waitFor(() => expect(screen.getByRole("button", { name: /start agent/i })).toBeEnabled());
    expect(screen.getByText(/simulated money/i)).toBeInTheDocument();
    expect(screen.getByLabelText("Maximum position size in units")).toBeInTheDocument();
    expect(screen.queryByText(/trades live only/i)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /start agent/i }));
    await waitFor(() => expect(startAgent).toHaveBeenCalledOnce());
  });

  it("does not present Practice as Live-ready when disabled", async () => {
    vi.mocked(getAgentStatus).mockResolvedValue({ ...IDLE, enabled: false, mode: "practice" });
    renderPanel();
    await waitFor(() => expect(screen.getByText("ai.autonomous_agent.enabled")).toBeInTheDocument());
    expect(screen.queryByText(/brokers.account_acls/)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /start agent/i })).toBeDisabled();
  });

  it("fails closed while status is unknown and on a status error", async () => {
    const status = deferred<typeof IDLE>();
    vi.mocked(getAgentStatus).mockReturnValue(status.promise);
    renderPanel();
    expect(screen.getByRole("button", { name: /start agent/i })).toBeDisabled();
    await act(async () => status.reject(new Error("Status service unavailable")));
    expect(await screen.findByText(/Status service unavailable/)).toBeInTheDocument();
    expect(screen.getByText("Status unavailable")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /start agent/i })).toBeDisabled();
    expect(screen.queryByText("Idle")).not.toBeInTheDocument();
  });

  it.each([
    ["Maximum position size in units", "0"],
    ["Maximum position size in units", "1.5"],
    ["Maximum position size in units", "2units"],
    ["Maximum position size in units", ""],
    ["Stop loss percent", "0"],
    ["Stop loss percent", "-1"],
    ["Stop loss percent", "2bad"],
    ["Take profit percent", "Infinity"],
    ["Take profit percent", ""],
  ])("rejects invalid %s input %j without a fallback", async (label, value) => {
    renderPanel();
    await waitFor(() => expect(screen.getByRole("button", { name: /start agent/i })).toBeEnabled());
    fireEvent.change(screen.getByLabelText(label), { target: { value } });
    fireEvent.click(screen.getByRole("button", { name: /start agent/i }));
    expect(screen.getByRole("alert")).toHaveTextContent(/positive/);
    expect(startAgent).not.toHaveBeenCalled();
  });

  it("shows waiting truthfully and keeps the stop control available", async () => {
    vi.mocked(getAgentStatus).mockResolvedValue({ ...RUNNING, mode: "practice", agent_status: "waiting" });
    renderPanel();
    expect(await screen.findByText("Waiting for market session")).toBeInTheDocument();
    expect(screen.queryByText("Running")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /stop & square off/i })).toBeEnabled();
    expect(screen.queryByRole("button", { name: /start agent/i })).not.toBeInTheDocument();
  });

  it("shows failed stop evidence and unresolved positions after the worker stops", async () => {
    vi.mocked(getAgentStatus).mockResolvedValue({
      ...RUNNING, mode: "practice", running: false, agent_status: "reconciliation_required",
      run_id: "practice-one", error: "Square-off failed: price unavailable",
    });
    vi.mocked(getPracticeAgentRuns).mockResolvedValue([{ ...PRACTICE_RUN, status: "reconciliation_required" }]);
    renderPanel();
    expect(await screen.findByText(/Square-off failed: price unavailable/)).toBeInTheDocument();
    expect(screen.getByRole("table", { name: "Agent positions" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /start agent/i })).toBeDisabled();
    expect(screen.getByText(/no automatic replay/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /resolve interrupted run/i })).toBeEnabled();
  });

  it("shows durable history and the selected run's ordered event evidence", async () => {
    vi.mocked(getPracticeAgentRuns).mockResolvedValue([PRACTICE_RUN, { ...PRACTICE_RUN, run_id: "practice-two" }]);
    vi.mocked(getPracticeAgentEvents).mockImplementation(async (runId) => [{
      seq: 1, run_id: runId, kind: "order_filled", data: { symbol: runId === "practice-one" ? "RELIANCE" : "ICICIBANK" },
      created_at: "2026-09-30T09:01:00Z",
    }]);
    renderPanel();
    expect(await screen.findByRole("heading", { name: "Practice run history" })).toBeInTheDocument();
    expect(await screen.findByText(/order_filled/)).toBeInTheDocument();
    expect(screen.getByText(/"symbol": "RELIANCE"/)).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Practice run"), { target: { value: "practice-two" } });
    expect(await screen.findByText(/"symbol": "ICICIBANK"/)).toBeInTheDocument();
    expect(screen.queryByText(/"symbol": "RELIANCE"/)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /resolve interrupted run/i })).not.toBeInTheDocument();
  });

  it("resolves only the selected interrupted run and surfaces a server flatness refusal", async () => {
    vi.mocked(getPracticeAgentRuns).mockResolvedValue([{ ...PRACTICE_RUN, status: "reconciliation_required" }]);
    vi.mocked(resolvePracticeAgentRun).mockRejectedValue(new Error("Practice account still has open positions"));
    renderPanel();
    const resolve = await screen.findByRole("button", { name: /resolve interrupted run/i });
    expect(screen.getByText(/server verifies.*flat/i)).toBeInTheDocument();
    fireEvent.click(resolve);
    expect(await screen.findByText("Practice account still has open positions")).toBeInTheDocument();
    expect(vi.mocked(resolvePracticeAgentRun).mock.calls[0][0]).toBe("practice-one");
    expect(screen.getByRole("button", { name: /start agent/i })).toBeDisabled();
  });

  it("does not reuse a previous mode's session while checking the new mode", async () => {
    const liveStatus = deferred<typeof IDLE>();
    vi.mocked(getAgentStatus).mockResolvedValueOnce({ ...RUNNING, mode: "practice" }).mockReturnValueOnce(liveStatus.promise);
    const panel = renderPanel();
    expect(await screen.findByRole("table", { name: "Agent positions" })).toBeInTheDocument();
    mockMode = "live";
    panel.rerenderMode();
    expect(screen.queryByRole("table", { name: "Agent positions" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /start agent/i })).toBeDisabled();
    await act(async () => liveStatus.resolve(IDLE));
    await waitFor(() => expect(screen.getByRole("button", { name: /start agent/i })).toBeEnabled());
    expect(getAgentStatus).toHaveBeenCalledTimes(2);
  });

  it("ignores a late mutation error after switching modes", async () => {
    const start = deferred<typeof RUNNING>();
    vi.mocked(startAgent).mockReturnValue(start.promise);
    const panel = renderPanel();
    await waitFor(() => expect(screen.getByRole("button", { name: /start agent/i })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: /start agent/i }));
    await waitFor(() => expect(startAgent).toHaveBeenCalledOnce());
    mockMode = "live";
    vi.mocked(getAgentStatus).mockResolvedValue(IDLE);
    panel.rerenderMode();
    await act(async () => start.reject(new Error("Old Practice start failed")));
    await waitFor(() => expect(screen.getByRole("button", { name: /start agent/i })).toBeEnabled());
    expect(screen.queryByText("Old Practice start failed")).not.toBeInTheDocument();
  });
});


describe("AgentPanel bounded Practice inputs and evidence", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockMode = "practice";
    vi.mocked(getAgentStatus).mockResolvedValue({ ...IDLE, mode: "practice" });
    vi.mocked(getPracticeAgentRuns).mockResolvedValue([]);
    vi.mocked(getPracticeAgentEvents).mockResolvedValue([]);
  });

  it.each([
    ["Maximum position size in units", "1000001"],
    ["Stop loss percent", "100.01"],
    ["Take profit percent", "101"],
    ["Agent symbols", Array.from({ length: 21 }, (_, i) => `STOCK${i}`).join(",")],
  ])("rejects out-of-range %s without submitting", async (label, value) => {
    renderPanel();
    await waitFor(() => expect(screen.getByRole("button", { name: /start agent/i })).toBeEnabled());
    fireEvent.change(screen.getByLabelText(label), { target: { value } });
    fireEvent.click(screen.getByRole("button", { name: /start agent/i }));
    expect(screen.getByRole("alert")).toBeInTheDocument();
    expect(startAgent).not.toHaveBeenCalled();
  });

  it("loads later events without losing previous evidence", async () => {
    vi.mocked(getPracticeAgentRuns).mockResolvedValue([PRACTICE_RUN]);
    vi.mocked(getPracticeAgentEvents).mockImplementation(async (runId, after = 0) => after === 0
      ? Array.from({ length: 100 }, (_, i) => ({ seq: i + 1, run_id: runId, kind: `event-${i + 1}`, data: {}, created_at: "now" }))
      : [{ seq: 101, run_id: runId, kind: "terminal-event", data: {}, created_at: "now" }]);
    renderPanel();
    fireEvent.click(await screen.findByRole("button", { name: "Load more events" }));
    expect(await screen.findByText(/terminal-event/)).toBeInTheDocument();
    expect(screen.getByText(/#1 · event-1 ·/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Load more events" })).not.toBeInTheDocument();
  });

  it("blocks starts if Practice history cannot establish unresolved-run state", async () => {
    vi.mocked(getPracticeAgentRuns).mockRejectedValue(new Error("History unavailable"));
    renderPanel();
    expect(await screen.findByText(/History unavailable/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /start agent/i })).toBeDisabled();
  });

  it("does not claim idle or allow starts for an unknown server lifecycle", async () => {
    vi.mocked(getAgentStatus).mockResolvedValue({ ...IDLE, mode: "practice", agent_status: "unrecognised" });
    renderPanel();
    expect(await screen.findByText("Unknown state: unrecognised")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /start agent/i })).toBeDisabled();
  });

  it("rejects a session-mode mismatch instead of exposing another mode's controls", async () => {
    vi.mocked(getAgentStatus).mockResolvedValue({ ...RUNNING, mode: "live" });
    renderPanel();
    expect(await screen.findByText("Mode mismatch")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /start agent/i })).toBeDisabled();
    expect(screen.queryByRole("button", { name: /stop & square off/i })).not.toBeInTheDocument();
  });

  it.each([IDLE, RUNNING])("rejects legacy mode-less Live status in the Practice panel (running=$running)", async (snapshot) => {
    vi.mocked(getAgentStatus).mockResolvedValue(snapshot);
    renderPanel();
    expect(await screen.findByText("Mode mismatch")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /start agent/i })).toBeDisabled();
    expect(screen.queryByRole("button", { name: /stop & square off/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("table", { name: "Agent positions" })).not.toBeInTheDocument();
  });

  it("keeps the backend stop failure visible when the status becomes failed", async () => {
    vi.mocked(getAgentStatus).mockResolvedValue({ ...RUNNING, mode: "practice" });
    vi.mocked(stopAgent).mockImplementation(async () => {
      vi.mocked(getAgentStatus).mockResolvedValue({ ...IDLE, mode: "practice", agent_status: "failed" });
      throw new Error("Could not confirm square-off");
    });
    renderPanel();
    fireEvent.click(await screen.findByRole("button", { name: /stop & square off/i }));
    expect(await screen.findByText("Could not confirm square-off")).toBeInTheDocument();
    expect(await screen.findByText("Failed")).toBeInTheDocument();
  });
});

describe("AgentPanel recovery and response races", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockMode = "practice";
    vi.mocked(getAgentStatus).mockResolvedValue({ ...IDLE, mode: "practice" });
    vi.mocked(getPracticeAgentRuns).mockResolvedValue([]);
    vi.mocked(getPracticeAgentEvents).mockResolvedValue([]);
  });

  it("blocks a new run while a stopped worker still reports positions", async () => {
    vi.mocked(getAgentStatus).mockResolvedValue({ ...RUNNING, mode: "practice", running: false, agent_status: "failed" });
    renderPanel();
    expect(await screen.findByRole("table", { name: "Agent positions" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /start agent/i })).toBeDisabled();
  });

  it.each(["starting", "waiting", "running", "stopping"])("resolves the stopped evidence-failed run when durable history remains %s", async (status) => {
    const interrupted = {
      ...IDLE, mode: "practice" as const, agent_status: "reconciliation_required",
      run_id: "practice-one", error: "Practice evidence storage failed; reconciliation is required",
    };
    vi.mocked(getAgentStatus).mockResolvedValue(interrupted);
    vi.mocked(getPracticeAgentRuns).mockResolvedValue([{ ...PRACTICE_RUN, status }]);
    const resolution = deferred<typeof interrupted>();
    vi.mocked(resolvePracticeAgentRun).mockReturnValue(resolution.promise);
    renderPanel();

    const resolve = await screen.findByRole("button", { name: /resolve interrupted run/i });
    expect(resolve).toBeEnabled();
    expect(screen.getByRole("button", { name: /start agent/i })).toBeDisabled();
    fireEvent.click(resolve);
    await waitFor(() => expect(resolvePracticeAgentRun).toHaveBeenCalledOnce());
    expect(vi.mocked(resolvePracticeAgentRun).mock.calls[0][0]).toBe("practice-one");
    expect(resolve).toBeDisabled();
    expect(screen.getByRole("button", { name: /start agent/i })).toBeDisabled();

    const stopped = { ...interrupted, agent_status: "stopped", error: "" };
    vi.mocked(getAgentStatus).mockResolvedValue(stopped);
    vi.mocked(getPracticeAgentRuns).mockResolvedValue([PRACTICE_RUN]);
    await act(async () => resolution.resolve(stopped));
    await waitFor(() => expect(screen.getByRole("button", { name: /start agent/i })).toBeEnabled());
    expect(screen.queryByRole("button", { name: /resolve interrupted run/i })).not.toBeInTheDocument();
  });

  it("does not apply a stopped snapshot's recovery action to another history run", async () => {
    vi.mocked(getAgentStatus).mockResolvedValue({
      ...IDLE, mode: "practice", agent_status: "reconciliation_required", run_id: "practice-one",
    });
    vi.mocked(getPracticeAgentRuns).mockResolvedValue([
      { ...PRACTICE_RUN, status: "running" },
      { ...PRACTICE_RUN, run_id: "practice-two", status: "running" },
    ]);
    renderPanel();
    expect(await screen.findByRole("button", { name: /resolve interrupted run/i })).toBeEnabled();
    fireEvent.change(screen.getByLabelText("Practice run"), { target: { value: "practice-two" } });
    expect(screen.queryByRole("button", { name: /resolve interrupted run/i })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /start agent/i })).toBeDisabled();
  });

  it.each([
    { mode: "live" as const, running: false },
    { mode: "practice" as const, running: true },
  ])("does not recover an active history row from an unsafe snapshot %j", async (snapshot) => {
    vi.mocked(getAgentStatus).mockResolvedValue({
      ...IDLE, ...snapshot, agent_status: "reconciliation_required", run_id: "practice-one",
    });
    vi.mocked(getPracticeAgentRuns).mockResolvedValue([{ ...PRACTICE_RUN, status: "running" }]);
    renderPanel();
    expect(await screen.findByLabelText("Practice run")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /resolve interrupted run/i })).not.toBeInTheDocument();
    expect(resolvePracticeAgentRun).not.toHaveBeenCalled();
  });

  it("refreshes final event evidence when history reports a completed run", async () => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    vi.mocked(getPracticeAgentRuns).mockResolvedValue([{ ...PRACTICE_RUN, status: "running" }]);
    vi.mocked(getPracticeAgentEvents).mockResolvedValue([
      { seq: 1, run_id: "practice-one", kind: "started", data: {}, created_at: "now" },
    ]);
    renderPanel(qc);
    expect(await screen.findByText(/#1 · started/)).toBeInTheDocument();
    vi.mocked(getPracticeAgentEvents).mockResolvedValue([
      { seq: 1, run_id: "practice-one", kind: "started", data: {}, created_at: "now" },
      { seq: 2, run_id: "practice-one", kind: "completed", data: {}, created_at: "later" },
    ]);
    act(() => qc.setQueryData(["aiAgent", "practice", "runs"], [{ ...PRACTICE_RUN, status: "completed", updated_at: "2026-09-30T09:40:00Z" }]));
    expect(await screen.findByText(/#2 · completed/)).toBeInTheDocument();
  });

  it("does not reopen a stale Practice session after switching away and back", async () => {
    const oldStart = deferred<typeof RUNNING>();
    vi.mocked(startAgent).mockReturnValue(oldStart.promise);
    const panel = renderPanel();
    await waitFor(() => expect(screen.getByRole("button", { name: /start agent/i })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: /start agent/i }));
    await waitFor(() => expect(startAgent).toHaveBeenCalledOnce());
    mockMode = "live";
    vi.mocked(getAgentStatus).mockResolvedValue(IDLE);
    panel.rerenderMode();
    await waitFor(() => expect(screen.getByRole("button", { name: /start agent/i })).toBeEnabled());
    mockMode = "practice";
    vi.mocked(getAgentStatus).mockResolvedValue({ ...IDLE, mode: "practice" });
    panel.rerenderMode();
    await waitFor(() => expect(screen.getByRole("button", { name: /start agent/i })).toBeEnabled());
    await act(async () => oldStart.resolve(RUNNING));
    expect(screen.getByText("Idle")).toBeInTheDocument();
    expect(screen.queryByRole("table", { name: "Agent positions" })).not.toBeInTheDocument();
  });
});

describe("AgentPanel legacy Live and busy history", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockMode = "live";
    vi.mocked(getPracticeAgentRuns).mockResolvedValue([]);
    vi.mocked(getPracticeAgentEvents).mockResolvedValue([]);
  });

  it("recognises legacy uppercase Live status values", async () => {
    vi.mocked(getAgentStatus).mockResolvedValue({ ...RUNNING, agent_status: "RUNNING" });
    renderPanel();
    expect(await screen.findByText("Running")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /stop & square off/i })).toBeEnabled();
  });

  it("shows legacy stop failure details after the worker exits", async () => {
    vi.mocked(getAgentStatus).mockResolvedValue({ ...IDLE, agent_status: "STOP_FAILED", stop_failure: "Live exit was refused" });
    renderPanel();
    expect(await screen.findByText("Stop failed")).toBeInTheDocument();
    expect(screen.getByText("Live exit was refused")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /start agent/i })).toBeDisabled();
  });

  it("blocks duplicate Practice starts when history still reports an active run", async () => {
    mockMode = "practice";
    vi.mocked(getAgentStatus).mockResolvedValue({ ...IDLE, mode: "practice" });
    vi.mocked(getPracticeAgentRuns).mockResolvedValue([{ ...PRACTICE_RUN, status: "waiting" }]);
    renderPanel();
    expect(await screen.findByLabelText("Practice run")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /start agent/i })).toBeDisabled();
  });
});


describe("AgentPanel operator entry rationale", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockMode = "practice";
    vi.mocked(getAgentStatus).mockResolvedValue({ ...IDLE, mode: "practice" });
    vi.mocked(getPracticeAgentRuns).mockResolvedValue([]);
    vi.mocked(getPracticeAgentEvents).mockResolvedValue([]);
    vi.mocked(startAgent).mockResolvedValue({ ...RUNNING, mode: "practice" });
  });

  it("starts with an empty optional Practice rationale and explains its limited authority", async () => {
    renderPanel();
    const field = screen.getByRole("textbox", { name: /operator entry rationale/i });
    expect(field).toHaveValue("");
    expect(field).toHaveAttribute("maxlength", "2000");
    expect(screen.getByText(/Laya still decides every entry/)).toHaveTextContent(/does not automatically accept clamps/);
    expect(screen.getByText(/Do not include credentials or secrets/)).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole("button", { name: /start agent/i })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: /start agent/i }));
    await waitFor(() => expect(startAgent).toHaveBeenCalledOnce());
    expect(vi.mocked(startAgent).mock.calls[0][0].entry_rationale).toBe("");
  });

  it("submits the operator's trimmed rationale without rewriting the plan", async () => {
    renderPanel();
    await waitFor(() => expect(screen.getByRole("button", { name: /start agent/i })).toBeEnabled());
    fireEvent.change(screen.getByRole("textbox", { name: /operator entry rationale/i }), {
      target: { value: "  Opening-range plan\nKeep the configured stop.  " },
    });
    fireEvent.click(screen.getByRole("button", { name: /start agent/i }));
    await waitFor(() => expect(startAgent).toHaveBeenCalledOnce());
    expect(vi.mocked(startAgent).mock.calls[0][0].entry_rationale).toBe("Opening-range plan\nKeep the configured stop.");
  });

  it("rejects an oversized rationale even if the browser input limit is bypassed", async () => {
    renderPanel();
    await waitFor(() => expect(screen.getByRole("button", { name: /start agent/i })).toBeEnabled());
    fireEvent.change(screen.getByRole("textbox", { name: /operator entry rationale/i }), { target: { value: "x".repeat(2001) } });
    fireEvent.click(screen.getByRole("button", { name: /start agent/i }));
    expect(screen.getByRole("alert")).toHaveTextContent(/rationale.*2,000 characters/i);
    expect(startAgent).not.toHaveBeenCalled();
  });

  it("keeps the rationale field and parameter out of Live starts", async () => {
    mockMode = "live";
    vi.mocked(getAgentStatus).mockResolvedValue(IDLE);
    vi.mocked(startAgent).mockResolvedValue(RUNNING);
    renderPanel();
    await waitFor(() => expect(screen.getByRole("button", { name: /start agent/i })).toBeEnabled());
    expect(screen.queryByRole("textbox", { name: /operator entry rationale/i })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /start agent/i }));
    await waitFor(() => expect(startAgent).toHaveBeenCalledOnce());
    expect(vi.mocked(startAgent).mock.calls[0][0]).not.toHaveProperty("entry_rationale");
  });

  it("shows the persisted operator rationale for the selected Practice run", async () => {
    vi.mocked(getPracticeAgentRuns).mockResolvedValue([{
      ...PRACTICE_RUN, config: { ...PRACTICE_RUN.config, entry_rationale: "Operator plan saved with this run" },
    }]);
    renderPanel();
    expect(await screen.findByText("Operator plan saved with this run")).toBeInTheDocument();
  });
});

describe("AgentPanel Practice model limits", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockMode = "practice";
    vi.mocked(getAgentStatus).mockResolvedValue({ ...IDLE, mode: "practice" });
    vi.mocked(getPracticeAgentRuns).mockResolvedValue([]);
    vi.mocked(getPracticeAgentEvents).mockResolvedValue([]);
    vi.mocked(startAgent).mockResolvedValue({ ...RUNNING, mode: "practice" });
  });

  it("submits the default Practice limits with the exact start payload", async () => {
    renderPanel();
    await waitFor(() => expect(screen.getByRole("button", { name: /start agent/i })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: /start agent/i }));
    await waitFor(() => expect(startAgent).toHaveBeenCalledOnce());
    expect(vi.mocked(startAgent).mock.calls[0][0]).toEqual({
      symbols: ["RELIANCE"], exchange: "NSE", max_position_size: 1,
      stop_loss_pct: 2, take_profit_pct: 4, entry_rationale: "",
      model_call_limit: 500, model_output_limit: 512,
    });
  });

  it("labels the default limits and explains their scope without inventing idle usage", async () => {
    renderPanel();
    expect(await screen.findByLabelText("Model call limit")).toHaveValue("500");
    expect(screen.getByLabelText("Output tokens per response")).toHaveValue("512");
    expect(screen.getByText(/analysis and reflection/)).toHaveTextContent(/not.*spend guarantee/i);
    expect(screen.getByText(/analysis and reflection/)).toHaveTextContent(/input tokens/i);
    expect(screen.queryByRole("region", { name: "Practice model usage" })).not.toBeInTheDocument();
  });

  it.each([[1, 16], [125, 256], [10000, 4096]])("submits exact custom Practice limits %i and %i", async (callLimit, outputLimit) => {
    renderPanel();
    await waitFor(() => expect(screen.getByRole("button", { name: /start agent/i })).toBeEnabled());
    fireEvent.change(screen.getByLabelText("Model call limit"), { target: { value: String(callLimit) } });
    fireEvent.change(screen.getByLabelText("Output tokens per response"), { target: { value: String(outputLimit) } });
    fireEvent.click(screen.getByRole("button", { name: /start agent/i }));
    await waitFor(() => expect(startAgent).toHaveBeenCalledOnce());
    expect(vi.mocked(startAgent).mock.calls[0][0]).toEqual({
      symbols: ["RELIANCE"], exchange: "NSE", max_position_size: 1,
      stop_loss_pct: 2, take_profit_pct: 4, entry_rationale: "",
      model_call_limit: callLimit, model_output_limit: outputLimit,
    });
  });

  it.each([
    ["Model call limit", ""], ["Model call limit", "0"], ["Model call limit", "10001"],
    ["Model call limit", "1.5"], ["Model call limit", "50calls"], ["Model call limit", "1e2"],
    ["Model call limit", "-1"], ["Model call limit", "Infinity"], ["Model call limit", "+50"],
    ["Output tokens per response", ""], ["Output tokens per response", "15"], ["Output tokens per response", "4097"],
    ["Output tokens per response", "512.5"], ["Output tokens per response", "512tokens"], ["Output tokens per response", "1e3"],
    ["Output tokens per response", "-16"], ["Output tokens per response", "Infinity"], ["Output tokens per response", "+512"],
  ])("rejects invalid %s %j without submitting or applying a fallback", async (label, value) => {
    renderPanel();
    await waitFor(() => expect(screen.getByRole("button", { name: /start agent/i })).toBeEnabled());
    fireEvent.change(screen.getByLabelText(label), { target: { value } });
    fireEvent.click(screen.getByRole("button", { name: /start agent/i }));
    expect(screen.getByRole("alert")).toHaveTextContent(label === "Model call limit"
      ? "Model call limit must be a whole number from 1 to 10,000."
      : "Output tokens per response must be a whole number from 16 to 4,096.");
    expect(startAgent).not.toHaveBeenCalled();
  });

  it.each([
    ["available", "Available", 37, 88],
    ["exhausted", "Exhausted", 125, 0],
    ["evidence_unavailable", "Evidence unavailable", 38, 87],
  ] as const)("shows backend counts and the %s budget status", async (status, label, used, remaining) => {
    vi.mocked(getAgentStatus).mockResolvedValue({
      ...RUNNING, mode: "practice", run_id: "practice-one",
      model_usage: {
        model_call_limit: 125, model_output_limit: 256,
        model_calls_used: used, model_calls_remaining: remaining, status,
      },
    });
    renderPanel();
    const usage = await screen.findByRole("region", { name: "Practice model usage" });
    expect(usage).toHaveTextContent(`${used} / 125 model calls used`);
    expect(usage).toHaveTextContent(`${remaining} model calls remaining`);
    expect(usage).toHaveTextContent("256 output tokens per response");
    expect(usage).toHaveTextContent(`Budget status: ${label}`);
    expect(usage).toHaveTextContent(/analysis and reflection/);
    expect(usage).toHaveTextContent(/not.*spend guarantee/i);
  });

  it("reports missing usage evidence without substituting configured defaults or zeroes", async () => {
    vi.mocked(getAgentStatus).mockResolvedValue({ ...RUNNING, mode: "practice" });
    renderPanel();
    const usage = await screen.findByRole("region", { name: "Practice model usage" });
    expect(usage).toHaveTextContent("Model usage evidence is unavailable for this run.");
    expect(usage).not.toHaveTextContent(/model calls used|model calls remaining|output tokens per response/);
  });

  it("retains backend usage for a stopped Practice run", async () => {
    vi.mocked(getAgentStatus).mockResolvedValue({
      ...IDLE, mode: "practice", run_id: "practice-one", agent_status: "stopped",
      model_usage: {
        model_call_limit: 125, model_output_limit: 256,
        model_calls_used: 37, model_calls_remaining: 88, status: "available",
      },
    });
    renderPanel();
    expect(await screen.findByRole("region", { name: "Practice model usage" })).toHaveTextContent("37 / 125 model calls used");
  });

  it("keeps model controls and parameters out of the exact Live start payload", async () => {
    mockMode = "live";
    vi.mocked(getAgentStatus).mockResolvedValue(IDLE);
    vi.mocked(startAgent).mockResolvedValue(RUNNING);
    renderPanel();
    await waitFor(() => expect(screen.getByRole("button", { name: /start agent/i })).toBeEnabled());
    expect(screen.queryByLabelText("Model call limit")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Output tokens per response")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /start agent/i }));
    await waitFor(() => expect(startAgent).toHaveBeenCalledOnce());
    expect(vi.mocked(startAgent).mock.calls[0][0]).toEqual({
      symbols: ["RELIANCE"], exchange: "NSE", max_position_size: 1, stop_loss_pct: 2, take_profit_pct: 4,
    });
  });

  it("does not present Practice model usage in a Live session", async () => {
    mockMode = "live";
    vi.mocked(getAgentStatus).mockResolvedValue({
      ...RUNNING, model_usage: {
        model_call_limit: 125, model_output_limit: 256,
        model_calls_used: 37, model_calls_remaining: 88, status: "available",
      },
    });
    renderPanel();
    expect(await screen.findByText("Running")).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Practice model usage" })).not.toBeInTheDocument();
  });
});
