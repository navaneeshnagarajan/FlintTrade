import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import "@testing-library/jest-dom";
vi.mock("@/components/NotificationCentre/useNotificationFeed", () => ({ emitNotification: vi.fn() }));
import { beforeEach, describe, expect, it, vi } from "vitest";

const runtime = vi.hoisted(() => ({
  mode: "live",
  apiKey: "",
  activeAccountId: "native:upstox:A" as string | null,
  accounts: [
    { account_id: "A", broker: "upstox", source: "native", status: "connected" },
    { account_id: "B", broker: "upstox", source: "native", status: "connected" },
  ],
}));

const api = vi.hoisted(() => ({
  getSafetyConfig: vi.fn(),
  activateKillSwitch: vi.fn(),
  resetKillSwitch: vi.fn(),
  getSafetyConfigForTarget: vi.fn(),
  resetDailyPnLState: vi.fn(),
  updateSafetyConfig: vi.fn(),
}));

vi.mock("@/stores/modeStore", () => ({
  useModeStore: Object.assign(
    (selector: (state: { mode: string }) => unknown) => selector({ mode: runtime.mode }),
    { getState: () => ({ mode: runtime.mode }) },
  ),
}));

vi.mock("@/stores/connectionStore", () => ({
  useConnectionStore: Object.assign(
    (selector: (state: { apiKey: string }) => unknown) => selector({
      apiKey: runtime.apiKey,
    }),
    {
      getState: () => ({
        apiKey: runtime.apiKey,
      }),
    },
  ),
}));

function accountMatches(
  account: { account_id: string; broker: string; source?: string },
  selector: string | null,
) {
  if (!selector) return false;
  return selector === `${account.source ?? "gateway"}:${account.broker}:${account.account_id}`;
}

vi.mock("@/stores/brokerStore", () => ({
  brokerAccountKey: (account: { account_id: string; broker: string; source?: string }) => (
    `${account.source ?? "gateway"}:${account.broker}:${account.account_id}`
  ),
  findBrokerAccountMatch: (
    accounts: Array<{ account_id: string; broker: string; source?: string }>,
    selector: string | null,
  ) => accounts.find((account) => accountMatches(account, selector)),
  useBrokerStore: Object.assign(
    (selector: (state: typeof runtime) => unknown) => selector(runtime),
    { getState: () => runtime },
  ),
}));

vi.mock("@/services/ftApi", () => ({
  getSafetyConfig: api.getSafetyConfig,
  activateKillSwitch: api.activateKillSwitch,
  resetKillSwitch: api.resetKillSwitch,
  getSafetyConfigForTarget: api.getSafetyConfigForTarget,
  resetDailyPnLState: api.resetDailyPnLState,
  updateSafetyConfig: api.updateSafetyConfig,
}));

import { RiskSection } from "../RiskSection";

const localSettings = {
  maxPositionLots: "10",
  mtmStoploss: "5000",
  mtmTarget: "10000",
  maxOrdersPerMinute: "20",
};

function safetyConfig(account: "A" | "B") {
  const isA = account === "A";
  return {
    check_market_hours: true,
    max_qty_nse: 1800,
    max_qty_nfo: 1800,
    max_qty_mcx: 100,
    max_positions: 10,
    max_margin_pct: 80,
    max_net_delta: 500,
    max_net_vega: 200,
    daily_loss_pause_pct: isA ? 3 : 4,
    daily_loss_kill_pct: isA ? 8 : 9,
    daily_loss_selector: `upstox:${account}`,
    opening_risk_capital: isA ? 100000 : 0,
    daily_loss_accounts: [],
    daily_loss_pause_active: isA,
    daily_loss_hard_stop_active: false,
    kill_switch_active: false,
    kill_switch_reason: "",
    flatten_complete: true,
    emergency_result: null,
  };
}

function createQueryClient() {
  return new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
}

function renderRiskSection(queryClient = createQueryClient()) {
  const rendered = render(
    <QueryClientProvider client={queryClient}>
      <RiskSection settings={localSettings} onChange={vi.fn()} />
    </QueryClientProvider>,
  );
  return { ...rendered, queryClient };
}

describe("RiskSection account-bound safety controls", () => {
  beforeEach(() => {
    runtime.mode = "live";
    runtime.apiKey = "";
    runtime.activeAccountId = "native:upstox:A";
    api.getSafetyConfig.mockReset().mockResolvedValue(safetyConfig("A"));
    api.getSafetyConfigForTarget.mockReset().mockImplementation(
      (target: { account_id: "A" | "B" }) => Promise.resolve(safetyConfig(target.account_id)),
    );
    api.resetDailyPnLState.mockReset().mockResolvedValue({
      selector: "upstox:A",
      session_key: "2026-07-13",
      opening_risk_capital: 100000,
      is_paused: false,
      is_killed: false,
    });
    api.updateSafetyConfig.mockReset().mockResolvedValue({ status: "success" });
  });

  it("rehydrates on account switch and binds reset/freeze to the displayed selector", async () => {
    const user = userEvent.setup();
    const { queryClient, rerender } = renderRiskSection();

    expect(await screen.findByText("native:upstox:A")).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByLabelText("Opening risk capital in INR")).toHaveValue(100000);
    });
    await user.click(screen.getByRole("button", { name: "Reset Daily-Loss Stop" }));
    expect(api.resetDailyPnLState).toHaveBeenCalledWith({ broker: "upstox", account_id: "A" });

    runtime.activeAccountId = "native:upstox:B";
    rerender(
      <QueryClientProvider client={queryClient}>
        <RiskSection settings={localSettings} onChange={vi.fn()} />
      </QueryClientProvider>,
    );

    expect(await screen.findByText("native:upstox:B")).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByLabelText("Daily loss pause threshold in percent")).toHaveValue(3);
      expect(screen.getByLabelText("Opening risk capital in INR")).toHaveValue(null);
    });
    expect(screen.queryByRole("button", { name: "Reset Daily-Loss Stop" })).not.toBeInTheDocument();
    expect(queryClient.getQueryData(["safetyConfig", "risk", "native:upstox:A"])).toBeDefined();
    expect(queryClient.getQueryData(["safetyConfig", "risk", "native:upstox:B"])).toBeDefined();

    await user.type(screen.getByLabelText("Opening risk capital in INR"), "250000");
    await user.click(screen.getByRole("button", { name: "Freeze" }));
    expect(api.updateSafetyConfig).toHaveBeenCalledWith(
      { opening_risk_capital: 250000 },
      { broker: "upstox", account_id: "B" },
    );
  });

  it("validates the positive pause/hard-stop relationship before calling the backend", async () => {
    const user = userEvent.setup();
    renderRiskSection();

    const pause = await screen.findByLabelText("Daily loss pause threshold in percent");
    const hardStop = screen.getByLabelText("Daily loss hard stop threshold in percent");
    await waitFor(() => expect(pause).toBeEnabled());
    await user.clear(pause);
    await user.type(pause, "5");
    await user.clear(hardStop);
    await user.type(hardStop, "4");
    await user.click(screen.getByRole("button", { name: "Sync Backend Daily-Loss Limits" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Daily-loss hard stop must be greater than the positive pause threshold",
    );
    expect(api.updateSafetyConfig).not.toHaveBeenCalled();
  });

  it("surfaces the backend's actionable error without claiming a local save", async () => {
    const user = userEvent.setup();
    api.updateSafetyConfig.mockRejectedValueOnce(new Error("Safety configuration requires restart"));
    renderRiskSection();

    await screen.findByText("native:upstox:A");
    await user.click(screen.getByRole("button", { name: "Sync Backend Daily-Loss Limits" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Safety configuration requires restart");
    expect(screen.queryByText(/saved locally/i)).not.toBeInTheDocument();
  });

  it("owns the process-wide emergency controls and all four global caps", async () => {
    renderRiskSection();
    expect(await screen.findByRole("heading", { name: "Kill Switch" })).toBeInTheDocument();
    for (const name of ["Max Positions", "Max Margin", "Max Net Delta", "Max Net Vega"]) {
      expect(await screen.findByRole("spinbutton", { name })).toBeInTheDocument();
    }
    expect(screen.getAllByLabelText("Daily loss pause threshold in percent")).toHaveLength(1);
    expect(screen.getAllByLabelText("Daily loss hard stop threshold in percent")).toHaveLength(1);
  });

  it("edits global daily-loss percentages in Live without a selected account", async () => {
    const user = userEvent.setup();
    runtime.activeAccountId = null;
    renderRiskSection();
    const pause = screen.getByLabelText("Daily loss pause threshold in percent");
    await waitFor(() => expect(pause).toHaveValue(3));
    expect(pause).toBeEnabled();
    expect(screen.getByLabelText("Opening risk capital in INR")).toBeDisabled();
    expect(screen.getByRole("button", { name: "Freeze" })).toBeDisabled();
    expect(api.getSafetyConfigForTarget).not.toHaveBeenCalled();
    await user.clear(pause);
    await user.type(pause, "4");
    await user.click(screen.getByRole("button", { name: "Sync Backend Daily-Loss Limits" }));
    await waitFor(() => expect(api.updateSafetyConfig).toHaveBeenCalledWith({
      daily_loss_pause_pct: 4,
      daily_loss_kill_pct: 8,
    }));
    expect(api.updateSafetyConfig.mock.calls[0]).toHaveLength(1);
  });

  it.each(["practice", "explore"])("disarms global and account safety writes in %s", async (mode) => {
    runtime.mode = mode;
    renderRiskSection();
    expect(screen.getByLabelText("Daily loss pause threshold in percent")).toBeDisabled();
    expect(screen.getByLabelText("Daily loss hard stop threshold in percent")).toBeDisabled();
    expect(screen.getByRole("button", { name: "Sync Backend Daily-Loss Limits" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Freeze" })).toBeDisabled();
    expect(api.getSafetyConfigForTarget).not.toHaveBeenCalled();
  });

  it("keeps global saves disabled without authoritative global safety state", async () => {
    api.getSafetyConfig.mockRejectedValue(new Error("Global safety unavailable"));
    renderRiskSection();
    await waitFor(() => expect(api.getSafetyConfigForTarget).toHaveBeenCalled());
    expect(screen.getByLabelText("Daily loss pause threshold in percent")).toBeDisabled();
    expect(screen.getByRole("button", { name: "Sync Backend Daily-Loss Limits" })).toBeDisabled();
  });

  it("wraps the safety action row on narrow surfaces", async () => {
    renderRiskSection();

    const syncButton = await screen.findByRole("button", { name: "Sync Backend Daily-Loss Limits" });
    expect(syncButton.parentElement).toHaveClass("flex-wrap");
  });
  it("does not block global thresholds when the selected account state fails", async () => {
    const user = userEvent.setup();
    api.getSafetyConfigForTarget.mockRejectedValue(new Error("Account state unavailable"));
    renderRiskSection();
    await screen.findByText("Account state unavailable");
    const pause = screen.getByLabelText("Daily loss pause threshold in percent");
    expect(pause).toBeEnabled();
    expect(screen.getByLabelText("Opening risk capital in INR")).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "Sync Backend Daily-Loss Limits" }));
    await waitFor(() => expect(api.updateSafetyConfig).toHaveBeenCalledWith({
      daily_loss_pause_pct: 3,
      daily_loss_kill_pct: 8,
    }));
  });

  it("requires matching account state for capital and latch reset", async () => {
    api.getSafetyConfigForTarget.mockResolvedValue({ ...safetyConfig("A"), daily_loss_selector: "upstox:B" });
    renderRiskSection();
    const reset = await screen.findByRole("button", { name: "Reset Daily-Loss Stop" });
    expect(reset).toBeDisabled();
    expect(screen.getByRole("button", { name: "Freeze" })).toBeDisabled();
    expect(screen.getByLabelText("Opening risk capital in INR")).toBeDisabled();
    expect(screen.getByLabelText("Daily loss pause threshold in percent")).toBeEnabled();
  });

  it("preserves an unsaved global threshold while the selected account changes", async () => {
    const user = userEvent.setup();
    const { rerender, queryClient } = renderRiskSection();
    const pause = screen.getByLabelText("Daily loss pause threshold in percent");
    await waitFor(() => expect(pause).toHaveValue(3));
    await user.clear(pause);
    await user.type(pause, "6");
    runtime.activeAccountId = "native:upstox:B";
    rerender(<QueryClientProvider client={queryClient}><RiskSection settings={localSettings} onChange={vi.fn()} /></QueryClientProvider>);
    await waitFor(() => expect(screen.getByLabelText("Opening risk capital in INR")).toHaveValue(null));
    expect(pause).toHaveValue(6);
  });
  it("keeps accepted global limits visible while the post-save refresh is pending", async () => {
    const user = userEvent.setup();
    api.getSafetyConfig.mockResolvedValueOnce(safetyConfig("A"))
      .mockReturnValue(new Promise(() => {}));
    renderRiskSection();
    const pause = screen.getByLabelText("Daily loss pause threshold in percent");
    await waitFor(() => expect(pause).toHaveValue(3));
    await user.clear(pause);
    await user.type(pause, "4");
    await user.click(screen.getByRole("button", { name: "Sync Backend Daily-Loss Limits" }));
    await screen.findByText("Backend daily-loss limits updated");
    expect(pause).toHaveValue(4);
  });

  it("disables percentage edits and repeat saves during a pending global save", async () => {
    const user = userEvent.setup();
    api.updateSafetyConfig.mockReturnValue(new Promise(() => {}));
    renderRiskSection();
    const pause = screen.getByLabelText("Daily loss pause threshold in percent");
    await waitFor(() => expect(pause).toHaveValue(3));
    await user.click(screen.getByRole("button", { name: "Sync Backend Daily-Loss Limits" }));
    expect(pause).toBeDisabled();
    expect(screen.getByLabelText("Daily loss hard stop threshold in percent")).toBeDisabled();
    expect(screen.getByRole("button", { name: "Syncing..." })).toBeDisabled();
  });
});
