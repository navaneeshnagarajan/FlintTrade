import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import "@testing-library/jest-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

const runtime = vi.hoisted(() => ({
  mode: "live",
  apiKey: "",
  openAlgoHydrated: true,
  activeAccountId: "native:upstox:A" as string | null,
  accounts: [
    { account_id: "A", broker: "upstox", source: "native", status: "connected" },
    { account_id: "B", broker: "upstox", source: "native", status: "connected" },
  ],
}));

const api = vi.hoisted(() => ({
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
    (selector: (state: { apiKey: string; openAlgoHydrated: boolean }) => unknown) => selector({
      apiKey: runtime.apiKey,
      openAlgoHydrated: runtime.openAlgoHydrated,
    }),
    {
      getState: () => ({
        apiKey: runtime.apiKey,
        openAlgoHydrated: runtime.openAlgoHydrated,
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
    runtime.openAlgoHydrated = true;
    runtime.activeAccountId = "native:upstox:A";
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
      expect(screen.getByLabelText("Daily loss pause threshold in percent")).toHaveValue(4);
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

  it("wraps the safety action row on narrow surfaces", async () => {
    renderRiskSection();

    const syncButton = await screen.findByRole("button", { name: "Sync Backend Daily-Loss Limits" });
    expect(syncButton.parentElement).toHaveClass("flex-wrap");
  });
});
