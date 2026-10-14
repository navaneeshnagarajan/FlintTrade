import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { runBacktest } from "../ftApi";
import { backtestReceiptFor } from "../backtestReceipt";
import TestingEvidencePanel from "@/routes/TestingEvidencePanel";
import { useAuthStore } from "@/stores/authStore";
import { useBrokerStore } from "@/stores/brokerStore";
import { useModeStore } from "@/stores/modeStore";
import { useConnectionStore } from "@/stores/connectionStore";
const runId = "existing.Run:2026-10_1";
const config = { symbol: "TEST", exchange: "NSE", interval: "1d", strategy: "EMACrossover", start_date: "", end_date: "", initial_capital: 100000, position_size_pct: 10 };
const result = { trades: [], equity_curve: [], final_equity: 100000, total_bars: 2, metrics: { total_return: 0, sharpe_ratio: 0, sortino_ratio: 0, max_drawdown: 0, win_rate: 0, profit_factor: 0, total_trades: 0, expectancy: 0 } };
const trial = "b".repeat(32), experiment = "a".repeat(32);
function response() { return new Response(JSON.stringify({ status: "success", data: result }), { headers: { "X-Trial-Id": trial, "X-Experiment-Id": experiment } }); }
beforeEach(() => {
  useAuthStore.setState(s => ({ status: "logged-in", username: "synthetic", token: "synthetic-selector", sessionGeneration: s.sessionGeneration + 1 }));
  useConnectionStore.setState({ apiKey: "synthetic-not-operator-authority" });
  useBrokerStore.setState({ activeAccountId: "unrelated-live-book" }); useModeStore.setState({ mode: "live" });
});
afterEach(() => vi.unstubAllGlobals());

it.each([false, true])("preserves the exact submitted selector and bearer for immutable=%s without claiming verified control scope", async immutable => {
  const input = { ...config, run_id: runId, ...(immutable ? { data_manifest_id: "f".repeat(64) } : {}) };
  const fetch = vi.fn(async (_url: string, _init?: RequestInit) => response()); vi.stubGlobal("fetch", fetch);
  const value = await runBacktest(input);
  expect(JSON.parse(String(fetch.mock.calls[0]?.[1]?.body))).toEqual(input);
  const headers = new Headers(fetch.mock.calls[0]?.[1]?.headers);
  expect(headers.get("Authorization")).toBe("Bearer synthetic-selector"); expect(headers.has("X-API-Key")).toBe(false);
  expect(backtestReceiptFor(value)).toMatchObject({ submittedRunId: runId, trialId: trial, experimentId: experiment });
  expect(useModeStore.getState().mode).toBe("live"); expect(useBrokerStore.getState().activeAccountId).toBe("unrelated-live-book");
});

it.each(["", " run", "run ", "a/b", "a\nb", "x".repeat(129)])("refuses malformed selector %j before transport", async run_id => {
  const fetch = vi.fn(async (_url: string, _init?: RequestInit) => response()); vi.stubGlobal("fetch", fetch);
  await expect(runBacktest({ ...config, run_id })).rejects.toThrow(); expect(fetch).not.toHaveBeenCalled();
});

it("refuses selector dispatch in preview without returning preview simulation", async () => {
  useAuthStore.setState({ token: "demo-user" });
  const fetch = vi.fn(async (_url: string, _init?: RequestInit) => response()); vi.stubGlobal("fetch", fetch);
  await expect(runBacktest({ ...config, run_id: runId })).rejects.toThrow(/preview/i); expect(fetch).not.toHaveBeenCalled();
});

it.each(["", runId])("mounts the history selector with exact blank omission for %j", async selected => {
  const sent: unknown[] = [];
  vi.stubGlobal("fetch", vi.fn(async (_url: string, init?: RequestInit) => {
    if (init?.method === "POST") { sent.push(JSON.parse(String(init.body))); return response(); }
    return new Response(JSON.stringify({ status: "success", data: { id: trial, experiment_id: experiment, status: "completed", evidence: {} } }));
  }));
  render(<TestingEvidencePanel />);
  const labels = { "History manifest ID": "f".repeat(64), "History instrument": "TEST", "History venue": "NSE", "History interval": "1d", "Backtest strategy": "EMACrossover", "Optional backtest run ID": selected };
  for (const [label, value] of Object.entries(labels)) fireEvent.change(screen.getByLabelText(label), { target: { value } });
  fireEvent.click(screen.getByRole("button", { name: "Run immutable backtest" }));
  await screen.findByLabelText("Exact core evidence");
  expect(sent).toEqual([{ ...config, data_manifest_id: "f".repeat(64), ...(selected ? { run_id: selected } : {}) }]);
  if (selected) expect(screen.getByLabelText("Captured backtest receipts")).toHaveTextContent(`Submitted run selector: ${selected} (not verified control scope)`);
});

it("retires selected-run backtest receipts after an account transition", async () => {
  let release!: (value: Response) => void;
  vi.stubGlobal("fetch", vi.fn(() => new Promise<Response>(resolve => { release = resolve; })));
  render(<TestingEvidencePanel />);
  const pending = runBacktest({ ...config, run_id: runId }); const refused = expect(pending).rejects.toThrow(/scope retired/);
  await act(async () => { useBrokerStore.setState({ activeAccountId: "other-live-book" }); release(response()); await refused; });
  expect(screen.getByLabelText("Captured backtest receipts")).not.toHaveTextContent(runId);
});
