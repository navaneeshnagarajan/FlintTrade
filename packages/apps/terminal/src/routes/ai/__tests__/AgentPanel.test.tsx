/**
 * AgentPanel.test — autonomous-agent control plane (start/stop/status).
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
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
}));
vi.mock("@/components/ui/GlassCard", () => ({
  GlassCard: ({ children, ...props }: Record<string, unknown>) => (
    <div {...props}>{children as React.ReactNode}</div>
  ),
}));

import AgentPanel from "../AgentPanel";
import { getAgentStatus, startAgent, stopAgent } from "@/services/ftApi";

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

function renderPanel() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <AgentPanel />
    </QueryClientProvider>,
  );
}

describe("AgentPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockMode = "live";
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

  it("blocks starting outside live mode with an honest hint", async () => {
    mockMode = "practice";
    vi.mocked(getAgentStatus).mockResolvedValue(IDLE);
    renderPanel();

    await waitFor(() =>
      expect(screen.getByText(/trades live only/i)).toBeInTheDocument(),
    );
    expect(screen.getByRole("button", { name: /start agent/i })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: /start agent/i }));
    expect(startAgent).not.toHaveBeenCalled();
  });
});
