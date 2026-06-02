import { describe, it, expect, vi, beforeEach, afterEach, type MockInstance } from "vitest";

const authState = vi.hoisted(() => ({
  token: "",
}));

// Mock connectionStore — ftApi reads ftApiKey/apiKey for X-API-Key header
vi.mock("@/stores/connectionStore", () => ({
  useConnectionStore: {
    getState: () => ({ ftApiKey: "test-ft-key", apiKey: "test-oa-key" }),
  },
}));
vi.mock("@/stores/authStore", () => ({
  useAuthStore: {
    getState: () => authState,
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
  let fetchSpy: MockInstance<typeof globalThis.fetch>;

  beforeEach(() => {
    authState.token = "";
    fetchSpy = vi.spyOn(globalThis, "fetch");
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  // ---- GET unwrapping ----

  it("get() unwraps response.data correctly", async () => {
    const strategies = [{ name: "SMA Cross", description: "Simple MA crossover", category: "trend", parameters: [] }];
    fetchSpy.mockResolvedValueOnce(
      jsonResponse({ status: "success", data: { strategies } }),
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
    expect(url).toContain("/api/v1/sentiment/analyse");
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

  it("runBacktest returns deterministic sample results without network in demo mode", async () => {
    authState.token = "demo-user";
    const config = {
      symbol: "NIFTY",
      exchange: "NFO",
      interval: "5m",
      start_date: "2024-01-01",
      end_date: "2024-12-31",
      strategy: "sma_crossover",
      initial_capital: 100000,
      position_size_pct: 10,
    };

    const result = await runBacktest(config);

    expect(fetchSpy).not.toHaveBeenCalled();
    expect(result.equity_curve.length).toBeGreaterThan(2);
    expect(result.trades.length).toBeGreaterThan(0);
    expect(result.final_equity).toBeGreaterThan(config.initial_capital);
    expect(result.metrics.total_trades).toBe(result.trades.length);
    expect(result.trades[0]).toMatchObject({
      symbol: "NIFTY",
      side: "BUY",
    });
  });

  // ---- getSafetyConfig flattens nested response ----

  it("getSafetyConfig() flattens nested 5-layer safety config", async () => {
    const raw = {
      l1_order: { price_deviation_pct: 5, check_market_hours: true, qty_limits: { NSE: 900, NFO: 1200, MCX: 50 } },
      l2_position: { max_positions: 8, max_margin_pct: 70 },
      l3_portfolio: { max_net_delta: 800, max_net_vega: 400 },
      l4_pnl: { pause_pct: 3, kill_pct: 6, is_paused: false, is_killed: false },
      l5_kill: { is_active: false, reason: "" },
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
      realized: 5000,
      unrealized: -200,
      total: 4800,
      max_total: 6000,
      min_total: 0,
      trade_count: 10,
      data_points: 100,
    };

    fetchSpy.mockResolvedValueOnce(
      jsonResponse({ status: "success", data: summary }),
    );

    const result = await getPnLSummary();

    expect(result).toHaveProperty("realized", 5000);
    expect(result).toHaveProperty("unrealized", -200);
    expect(result).toHaveProperty("total", 4800);
    expect(result).toHaveProperty("max_total", 6000);
    expect(result).toHaveProperty("min_total", 0);
    expect(result).toHaveProperty("trade_count");
    expect(result).toHaveProperty("data_points");
  });

  // ---- getSecuritySettings fields ----

  it("getSecuritySettings() returns all expected fields", async () => {
    const settings = {
      auto_ban_enabled: true,
      ban_threshold: 50,
      notfound_ban_threshold: 100,
      ban_duration: 3600,
    };

    fetchSpy.mockResolvedValueOnce(
      jsonResponse({ status: "success", data: settings }),
    );

    const result = await getSecuritySettings();

    expect(result).toEqual(settings);
    expect(typeof result.auto_ban_enabled).toBe("boolean");
    expect(typeof result.ban_threshold).toBe("number");
    expect(typeof result.notfound_ban_threshold).toBe("number");
    expect(typeof result.ban_duration).toBe("number");
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
