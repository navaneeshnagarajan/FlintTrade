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
  getSecuritySettings,
  analyzeSentiment,
  getCronJobs,
  getAuditLogs,
  getBannedIPs,
  activateKillSwitch,
  resetKillSwitch,
  getHealth,
  getEarningsCalendar,
  getPortfolioRRGData,
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

  it("getEarningsCalendar() normalises the backend events contract", async () => {
    fetchSpy.mockResolvedValueOnce(
      jsonResponse({
        status: "success",
        data: {
          events: [
            {
              symbol: "INFY",
              company_name: "Infosys Ltd",
              date: "2026-07-15",
              result: "meet",
              estimated_eps: 18.5,
              actual_eps: 18.6,
            },
          ],
        },
      }),
    );

    const result = await getEarningsCalendar(2026, 7);

    expect(fetchSpy).toHaveBeenCalledOnce();
    expect((fetchSpy.mock.calls[0] as [string, RequestInit])[0]).toContain(
      "/api/v1/earnings/calendar?year=2026&month=7",
    );
    expect(result.entries).toEqual([
      {
        symbol: "INFY",
        company: "Infosys Ltd",
        date: "2026-07-15",
        result: "inline",
        estimate: 18.5,
        actual: 18.6,
        sector: "IT",
      },
    ]);
  });

  it("getPortfolioRRGData() calls the backend portfolio RRG route through ftApi", async () => {
    fetchSpy.mockResolvedValueOnce(
      jsonResponse({
        status: "success",
        data: { benchmark: "NIFTY 50", tail_length: 8, is_sample_data: true, sectors: [] },
      }),
    );

    const result = await getPortfolioRRGData(["RELIANCE", "TCS"], 8);

    expect(fetchSpy).toHaveBeenCalledOnce();
    expect((fetchSpy.mock.calls[0] as [string, RequestInit])[0]).toContain(
      "/api/v1/rrg/portfolio?symbols=RELIANCE%2CTCS&tail_length=8",
    );
    expect(result).toEqual({ benchmark: "NIFTY 50", tail_length: 8, is_sample_data: true, sectors: [] });
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

  it("getBannedIPs maps the monitor's raw row to the table contract", async () => {
    fetchSpy.mockResolvedValueOnce(
      jsonResponse({
        status: "success",
        data: {
          bans: [
            { ip: "1.2.3.4", ban_reason: "404 flood", ban_expires: null, first_seen: 1700000000, last_seen: 1700000123 },
            { ip: "5.6.7.8", ban_reason: null, ban_expires: 1700001000, first_seen: 1700000500, last_seen: 1700000600 },
          ],
        },
      }),
    );

    const { bans } = await getBannedIPs();
    // ban_reason -> reason; last_seen (epoch s) -> ISO banned_at
    expect(bans[0]).toEqual({
      ip: "1.2.3.4",
      reason: "404 flood",
      banned_at: new Date(1700000123 * 1000).toISOString(),
    });
    // null ban_reason falls back to a readable label
    expect(bans[1].reason).toBe("Auto-ban");
  });

  it("getAuditLogs targets the bare /v1/audit/events route with date/limit/offset", async () => {
    fetchSpy.mockResolvedValueOnce(
      jsonResponse({ status: "success", data: { logs: [], total: 0 } }),
    );

    await getAuditLogs("2026-04-19", 50, 100);

    const url = fetchSpy.mock.calls[0]![0] as string;
    // Bare /v1 family (getV1), NOT /api/v1 — the route registers at /v1/audit.
    expect(url).toBe("/ft-api/v1/audit/events?date=2026-04-19&limit=50&offset=100");
  });
});
