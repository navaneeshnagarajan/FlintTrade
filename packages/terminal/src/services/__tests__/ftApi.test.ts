import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

// Mock connectionStore — ftApi reads ftApiKey/apiKey for X-API-Key header
vi.mock("@/stores/connectionStore", () => ({
  useConnectionStore: {
    getState: () => ({ ftApiKey: "test-ft-key", apiKey: "test-oa-key" }),
  },
}));
import {
  getStrategies,
  runBacktest,
  getSafetyConfig,
  getPnLSummary,
  getSecuritySettings,
  analyzeSentiment,
  getCronJobs,
  getAuditLogs,
  activateKillSwitch,
  resetKillSwitch,
  getHealth,
} from "../ftApi";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("FlintTrade API client (ftApi.ts)", () => {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  let fetchSpy: any;

  beforeEach(() => {
    fetchSpy = vi.spyOn(globalThis, "fetch");
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  // ---- GET unwrapping ----

  it("get() unwraps response.data correctly", async () => {
    const strategies = [{ name: "SMA Cross", description: "Simple MA crossover", category: "trend", parameters: [] }];
    fetchSpy.mockResolvedValueOnce(
      jsonResponse({ status: "success", data: strategies }),
    );

    const result = await getStrategies();
    expect(result).toEqual(strategies);
  });

  it("get() returns raw json when data key is absent", async () => {
    fetchSpy.mockResolvedValueOnce(
      jsonResponse({ status: "success", score: 42 }),
    );

    // getHealth returns whatever parseResponse produces
    const result = await getHealth();
    expect(result).toHaveProperty("score", 42);
  });

  // ---- POST sends JSON body ----

  it("post() sends JSON body with Content-Type header", async () => {
    fetchSpy.mockResolvedValueOnce(
      jsonResponse({ status: "success", data: { score: 0.8, label: "bullish", confidence: 0.9 } }),
    );

    await analyzeSentiment("Markets looking strong today");

    expect(fetchSpy).toHaveBeenCalledOnce();
    const [url, init] = fetchSpy.mock.calls[0] as [string, RequestInit];
    expect(url).toContain("/api/v1/sentiment/analyze");
    expect(init.method).toBe("POST");
    expect(init.headers).toEqual(
      expect.objectContaining({ "Content-Type": "application/json" }),
    );
    const body = JSON.parse(init.body as string);
    expect(body).toEqual({ text: "Markets looking strong today" });
  });

  it("post() sends body for backtest config", async () => {
    const config = {
      symbol: "NIFTY",
      exchange: "NSE",
      interval: "5m",
      start_date: "2025-01-01",
      end_date: "2025-03-01",
      strategy: "SMA Cross",
      initial_capital: 100000,
      position_size_pct: 10,
    };

    fetchSpy.mockResolvedValueOnce(
      jsonResponse({
        status: "success",
        data: {
          trades: [],
          equity_curve: [],
          metrics: { total_return: 0, sharpe_ratio: 0, sortino_ratio: 0, max_drawdown: 0, win_rate: 0, profit_factor: 0, total_trades: 0, expectancy: 0 },
          final_equity: 100000,
          total_bars: 500,
        },
      }),
    );

    const result = await runBacktest(config);
    expect(result).toHaveProperty("final_equity", 100000);
    expect(result).toHaveProperty("trades");
    expect(result).toHaveProperty("metrics");

    const sentBody = JSON.parse(
      (fetchSpy.mock.calls[0] as [string, RequestInit])[1].body as string,
    );
    expect(sentBody.symbol).toBe("NIFTY");
    expect(sentBody.strategy).toBe("SMA Cross");
  });

  // ---- getSafetyConfig flattens nested response ----

  it("getSafetyConfig() flattens nested 5-layer safety config", async () => {
    const raw = {
      l1_order: { price_deviation_pct: 5, check_market_hours: true, qty_limits: { NSE: 900, NFO: 1200, MCX: 50 } },
      l2_position: { max_positions: 8 },
      l3_portfolio: { max_margin_pct: 70, max_net_delta: 800, max_net_vega: 400 },
      l4_pnl: { pnl_pause_pct: 3, pnl_kill_pct: 6 },
      l5_kill: { active: false },
    };

    fetchSpy.mockResolvedValueOnce(
      jsonResponse({ status: "success", data: raw }),
    );

    const result = await getSafetyConfig();

    expect(result).toEqual({
      check_market_hours: true,
      max_qty_nse: 900,
      max_qty_nfo: 1200,
      max_qty_mcx: 50,
      max_positions: 8,
      max_margin_pct: 70,
      max_net_delta: 800,
      max_net_vega: 400,
      daily_loss_pause_pct: 3,
      daily_loss_kill_pct: 6,
      kill_switch_active: false,
    });
  });

  it("getSafetyConfig() applies defaults for missing nested fields", async () => {
    // Simulate a sparse response — some layers missing or incomplete
    const raw = {
      l1_order: {},
      l2_position: {},
      l3_portfolio: {},
      l4_pnl: {},
      l5_kill: {},
    };

    fetchSpy.mockResolvedValueOnce(
      jsonResponse({ status: "success", data: raw }),
    );

    const result = await getSafetyConfig();

    expect(result.check_market_hours).toBe(true);
    expect(result.max_qty_nse).toBe(1800);
    expect(result.max_qty_nfo).toBe(1800);
    expect(result.max_qty_mcx).toBe(100);
    expect(result.max_positions).toBe(10);
    expect(result.max_margin_pct).toBe(80);
    expect(result.max_net_delta).toBe(1000);
    expect(result.max_net_vega).toBe(500);
    expect(result.daily_loss_pause_pct).toBe(2);
    expect(result.daily_loss_kill_pct).toBe(5);
    expect(result.kill_switch_active).toBe(false);
  });

  // ---- getPnLSummary shape ----

  it("getPnLSummary() returns correct shape", async () => {
    const summary = {
      realized_pnl: 5000,
      unrealized_pnl: -200,
      total_pnl: 4800,
      max_drawdown: 1200,
      peak_pnl: 6000,
      entries: [{ timestamp: "2026-04-08T10:00:00", realized_pnl: 5000, unrealized_pnl: -200, total_pnl: 4800 }],
    };

    fetchSpy.mockResolvedValueOnce(
      jsonResponse({ status: "success", data: summary }),
    );

    const result = await getPnLSummary();

    expect(result).toHaveProperty("realized_pnl", 5000);
    expect(result).toHaveProperty("unrealized_pnl", -200);
    expect(result).toHaveProperty("total_pnl", 4800);
    expect(result).toHaveProperty("max_drawdown", 1200);
    expect(result).toHaveProperty("peak_pnl", 6000);
    expect(result.entries).toHaveLength(1);
  });

  // ---- getSecuritySettings fields ----

  it("getSecuritySettings() returns all expected fields", async () => {
    const settings = {
      auto_ban_enabled: true,
      threshold_404: 50,
      ban_duration_404: 3600,
      threshold_api: 100,
      ban_duration_api: 7200,
      repeat_offender_limit: 3,
    };

    fetchSpy.mockResolvedValueOnce(
      jsonResponse({ status: "success", data: settings }),
    );

    const result = await getSecuritySettings();

    expect(result).toEqual(settings);
    expect(typeof result.auto_ban_enabled).toBe("boolean");
    expect(typeof result.threshold_404).toBe("number");
    expect(typeof result.ban_duration_404).toBe("number");
    expect(typeof result.threshold_api).toBe("number");
    expect(typeof result.ban_duration_api).toBe("number");
    expect(typeof result.repeat_offender_limit).toBe("number");
  });

  // ---- Error handling ----

  it("throws on HTTP 401", async () => {
    fetchSpy.mockResolvedValueOnce(jsonResponse({}, 401));

    await expect(getStrategies()).rejects.toThrow("HTTP 401");
  });

  it("throws on HTTP 403", async () => {
    fetchSpy.mockResolvedValueOnce(jsonResponse({}, 403));

    await expect(activateKillSwitch("emergency")).rejects.toThrow("HTTP 403");
  });

  it("throws on HTTP 500", async () => {
    fetchSpy.mockResolvedValueOnce(jsonResponse({}, 500));

    await expect(getCronJobs()).rejects.toThrow("HTTP 500");
  });

  it("throws on status: error in JSON body", async () => {
    fetchSpy.mockResolvedValueOnce(
      jsonResponse({ status: "error", message: "Strategy not found" }),
    );

    await expect(getStrategies()).rejects.toThrow("Strategy not found");
  });

  it("throws generic message when status is error but no message", async () => {
    fetchSpy.mockResolvedValueOnce(
      jsonResponse({ status: "error" }),
    );

    await expect(getAuditLogs()).rejects.toThrow("FT API");
  });

  // ---- DELETE method ----

  it("delete sends DELETE method (resetKillSwitch)", async () => {
    fetchSpy.mockResolvedValueOnce(
      jsonResponse({ status: "success", data: { status: "ok" } }),
    );

    await resetKillSwitch();

    const [url, init] = fetchSpy.mock.calls[0] as [string, RequestInit];
    expect(url).toContain("/api/v1/safety/kill-switch");
    expect(init.method).toBe("DELETE");
  });

  // ---- URL construction ----

  it("constructs correct URL with /ft-api prefix in dev mode", async () => {
    fetchSpy.mockResolvedValueOnce(
      jsonResponse({ status: "success", data: { jobs: [] } }),
    );

    await getCronJobs();

    const url = fetchSpy.mock.calls[0]![0] as string;
    // In test (DEV=true), base is /ft-api
    expect(url).toBe("/ft-api/api/v1/cron/jobs");
  });
});
