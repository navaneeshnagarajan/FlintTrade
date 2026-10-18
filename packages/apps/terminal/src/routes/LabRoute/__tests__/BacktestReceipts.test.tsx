import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router";
import { afterEach, expect, it, vi } from "vitest";
import { BacktestSection } from "../BacktestSection";
import TestingEvidencePanel from "@/routes/TestingEvidencePanel";
import { useAuthStore } from "@/stores/authStore";
import { useBrokerStore } from "@/stores/brokerStore";
import { useModeStore } from "@/stores/modeStore";
import { useConnectionStore } from "@/stores/connectionStore";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
it("the existing Backtest widget publishes automatic immutable receipts while delivering its unchanged result", async () => {
  useAuthStore.setState(s => ({ status: "logged-in", token: "synthetic-mounted", username: "synthetic", sessionGeneration: s.sessionGeneration + 1 }));
  useBrokerStore.setState({ activeAccountId: "native:dhan:synthetic" });
  useModeStore.setState({ mode: "live" });
  useConnectionStore.setState({ apiKey: "" });
  const result = { trades: [], equity_curve: [], final_equity: 100000, total_bars: 2, metrics: { total_return: 0, sharpe_ratio: 0, sortino_ratio: 0, max_drawdown: 0, win_rate: 0, profit_factor: 0, total_trades: 0, expectancy: 0 } };
  const experiment = "a".repeat(32); const trial = "b".repeat(32);
  const unexpected: string[] = [];
  const fetch = vi.fn(async (url: string, init: RequestInit = {}) => {
    try {
      if (url === "/ft-api/api/v1/backtest/strategies" && (!init.method || init.method === "GET")) {
        return new Response(JSON.stringify({ status: "success", data: { strategies: [{ name: "EMACrossover", description: "Synthetic catalogue contract" }] } }));
      }
      expect(url).toBe("/ft-api/api/v1/backtest/run"); expect(init.method).toBe("POST");
      expect(JSON.parse(String(init.body))).toEqual({ symbol: "NIFTY", exchange: "NFO", interval: "5m", start_date: "2024-01-01", end_date: "2024-12-31", strategy: "EMACrossover", initial_capital: 100000, position_size_pct: 10 });
      expect(new Headers(init.headers).get("Authorization")).toBe("Bearer synthetic-mounted");
      return new Response(JSON.stringify({ status: "success", data: result }), { headers: { "X-Experiment-Id": experiment, "X-Trial-Id": trial } });
    } catch (error) { unexpected.push(String(error)); throw error; }
  });
  vi.stubGlobal("fetch", fetch);
  const query = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  const onResult = vi.fn();
  try {
    render(<QueryClientProvider client={query}><MemoryRouter initialEntries={["/lab?strategy=EMACrossover"]}><BacktestSection onResult={onResult} lastResult={null} /><TestingEvidencePanel /></MemoryRouter></QueryClientProvider>);
    const user = userEvent.setup();
    await waitFor(() => expect(screen.getByRole("button", { name: "Run Backtest" })).toBeEnabled());
    await user.click(screen.getByRole("button", { name: "Run Backtest" }));
    await waitFor(() => expect(onResult).toHaveBeenCalledWith(result, "EMACrossover"));
    expect(screen.getByLabelText("Captured backtest receipts")).toHaveTextContent(trial);
    expect(screen.getByLabelText("Captured backtest receipts")).toHaveTextContent(experiment);
    expect(fetch).toHaveBeenCalledTimes(2);
    expect(useModeStore.getState().mode).toBe("live");
    expect(useBrokerStore.getState().activeAccountId).toBe("native:dhan:synthetic");
  } finally { cleanup(); query.clear(); expect(unexpected).toEqual([]); }
});
