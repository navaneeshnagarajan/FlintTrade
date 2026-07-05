/**
 * HealthWidget.test.tsx
 *
 * Tests for the System Health utility widget.
 * Covers: initial render, status display, alert generation, auto-refresh.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, act } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import "@testing-library/jest-dom";

const { mockDirectBrokerConnected } = vi.hoisted(() => ({
  mockDirectBrokerConnected: { value: false },
}));

// ---------------------------------------------------------------------------
// Mocks — factories must not reference outer variables (Vitest hoisting rule)
// ---------------------------------------------------------------------------

vi.mock("@/services/api", () => ({
  ping: vi.fn().mockResolvedValue({ status: "ok" }),
}));

vi.mock("@/services/ftApi", () => ({
  getHealth: vi.fn().mockResolvedValue({
    status: "ok",
    broker: { status: "ok" },
    duckdb: { status: "ok" },
    disk: { status: "ok", free_gb: 120, total_gb: 500, used_pct: 24 },
    memory: { status: "ok", used_mb: 2048, total_mb: 16384, used_pct: 12.5 },
  }),
  getTrafficStats: vi.fn().mockResolvedValue({
    window_minutes: 5,
    total_requests: 420,
    requests_per_sec: 1.4,
    error_rate: 0.002,
    avg_latency_ms: 38,
    top_paths: [{ path: "/api/v1/quotes", count: 210 }],
  }),
  getLatencyStats: vi.fn().mockResolvedValue({
    "broker-a": { count: 100, avg_ms: 45, p50_ms: 40, p95_ms: 90, p99_ms: 140 },
  }),
  getSecurityStats: vi.fn().mockResolvedValue({
    total_ips: 3,
    banned_count: 0,
    top_offenders: [],
  }),
}));

// Zustand connection store mock
type MockStore = { status: string; wsConnected: boolean; lastPing: number | null; apiKey: string };
let mockStoreState: MockStore = {
  status: "connected",
  wsConnected: true,
  lastPing: Date.now() - 5000,
  apiKey: "test-openalgo-key",
};

vi.mock("@/stores/connectionStore", () => ({
  useConnectionStore: (selector?: (s: MockStore) => unknown) => {
    if (typeof selector === "function") return selector(mockStoreState);
    return mockStoreState;
  },
}));

vi.mock("@/hooks/useBrokerConnected", () => ({
  useDirectBrokerConnected: () => mockDirectBrokerConnected.value,
}));

// ---------------------------------------------------------------------------
// Import mocked functions after vi.mock declarations
// ---------------------------------------------------------------------------

import * as apiMod from "@/services/api";
import * as ftMod  from "@/services/ftApi";

const mockPing        = vi.mocked(apiMod.ping);
const mockGetHealth   = vi.mocked(ftMod.getHealth);
const mockGetTraffic  = vi.mocked(ftMod.getTrafficStats);
const mockGetLatency  = vi.mocked(ftMod.getLatencyStats);
const mockGetSecurity = vi.mocked(ftMod.getSecurityStats);

// ---------------------------------------------------------------------------
// Healthy baseline fixtures
// ---------------------------------------------------------------------------

const HEALTHY_SYSTEM: Awaited<ReturnType<typeof ftMod.getHealth>> = {
  status: "ok",
  broker: { status: "ok" },
  duckdb: { status: "ok" },
  disk: { status: "ok", free_gb: 120, total_gb: 500, used_pct: 24 },
  memory: { status: "ok", used_mb: 2048, total_mb: 16384, used_pct: 12.5 },
};

const HEALTHY_TRAFFIC: Awaited<ReturnType<typeof ftMod.getTrafficStats>> = {
  window_minutes: 5,
  total_requests: 420,
  requests_per_sec: 1.4,
  error_rate: 0.002,
  avg_latency_ms: 38,
  top_paths: [{ path: "/api/v1/quotes", count: 210 }],
};

const HEALTHY_LATENCY: Awaited<ReturnType<typeof ftMod.getLatencyStats>> = {
  "broker-a": { count: 100, avg_ms: 45, p50_ms: 40, p95_ms: 90, p99_ms: 140 },
};

const HEALTHY_SECURITY: Awaited<ReturnType<typeof ftMod.getSecurityStats>> = {
  total_ips: 3,
  banned_count: 0,
  top_offenders: [],
};

function resetToHealthy() {
  mockPing.mockResolvedValue({ status: "ok" });
  mockGetHealth.mockResolvedValue(HEALTHY_SYSTEM);
  mockGetTraffic.mockResolvedValue(HEALTHY_TRAFFIC);
  mockGetLatency.mockResolvedValue(HEALTHY_LATENCY);
  mockGetSecurity.mockResolvedValue(HEALTHY_SECURITY);
}

// ---------------------------------------------------------------------------
// Import component (after all mocks)
// ---------------------------------------------------------------------------

import HealthWidget from "../HealthWidget";

// ---------------------------------------------------------------------------
// Helper: render + flush all pending async work
// ---------------------------------------------------------------------------

async function renderWidget() {
  let result!: ReturnType<typeof render>;
  await act(async () => {
    result = render(<HealthWidget />);
  });
  return result;
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("HealthWidget", () => {
  beforeEach(() => {
    resetToHealthy();
    mockStoreState = {
      status: "connected",
      wsConnected: true,
      lastPing: Date.now() - 5000,
      apiKey: "test-openalgo-key",
    };
    mockDirectBrokerConnected.value = false;
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  // ---- Basic render --------------------------------------------------------

  it("renders the widget heading", async () => {
    await renderWidget();
    expect(screen.getByText("System Health")).toBeInTheDocument();
  });

  it("renders the Connections section heading", async () => {
    await renderWidget();
    // Use exact match on the uppercase label text
    expect(screen.getByText("Connections")).toBeInTheDocument();
  });

  it("renders the System section heading (uppercase label)", async () => {
    await renderWidget();
    expect(screen.getByText("System")).toBeInTheDocument();
  });

  it("renders the Performance section heading", async () => {
    await renderWidget();
    expect(screen.getByText("Performance")).toBeInTheDocument();
  });

  it("renders the Security section heading", async () => {
    await renderWidget();
    expect(screen.getByText("Security")).toBeInTheDocument();
  });

  it("renders the Session section heading", async () => {
    await renderWidget();
    expect(screen.getByText("Session")).toBeInTheDocument();
  });

  it("renders the auto-refresh footer note", async () => {
    await renderWidget();
    expect(screen.getByText(/auto-refreshes every 30/i)).toBeInTheDocument();
  });

  it("renders the refresh button with accessible label", async () => {
    await renderWidget();
    expect(screen.getByRole("button", { name: /refresh/i })).toBeInTheDocument();
  });

  it("widget container has correct data-testid", async () => {
    await renderWidget();
    expect(screen.getByTestId("health-widget")).toBeInTheDocument();
  });

  // ---- All systems OK banner -----------------------------------------------

  it("shows 'All systems operational' after successful data fetch", async () => {
    await renderWidget();
    // Data is loaded inside act(async...) — banner should be present synchronously
    expect(screen.getByText(/all systems operational/i)).toBeInTheDocument();
  });

  // ---- Connection status rows ----------------------------------------------

  it("shows Broker session row", async () => {
    await renderWidget();
    expect(screen.getByText("Broker session")).toBeInTheDocument();
  });

  it("shows OpenAlgo bridge row", async () => {
    await renderWidget();
    expect(screen.getByText("OpenAlgo bridge")).toBeInTheDocument();
  });

  it("does not mark OpenAlgo online when only a native broker session is connected", async () => {
    mockStoreState = { ...mockStoreState, status: "disconnected", apiKey: "" };
    mockDirectBrokerConnected.value = true;

    await renderWidget();

    expect(mockPing).not.toHaveBeenCalled();
    expect(screen.getByText("Broker session")).toBeInTheDocument();
    expect(screen.getByText("OpenAlgo bridge")).toBeInTheDocument();
    expect(screen.getByText("Degraded")).toBeInTheDocument();
  });

  it("shows WebSocket row", async () => {
    await renderWidget();
    expect(screen.getByText("WebSocket")).toBeInTheDocument();
  });

  it("shows FlintTrade Backend row", async () => {
    await renderWidget();
    expect(screen.getByText("FlintTrade Backend")).toBeInTheDocument();
  });

  // ---- WS disconnected alert -----------------------------------------------

  it("shows WebSocket disconnected alert when WS is down", async () => {
    mockStoreState = { ...mockStoreState, wsConnected: false };
    await renderWidget();
    expect(screen.getByText("WebSocket disconnected")).toBeInTheDocument();
  });

  // ---- Backend error alert -------------------------------------------------

  it("shows FT backend alert when health returns error status", async () => {
    mockGetHealth.mockResolvedValue({ ...HEALTHY_SYSTEM, status: "error" });
    await renderWidget();
    expect(screen.getByText("FT backend unreachable")).toBeInTheDocument();
  });

  // ---- Disk usage critical alert -------------------------------------------

  it("shows disk critical alert when disk usage > 90 %", async () => {
    mockGetHealth.mockResolvedValue({
      ...HEALTHY_SYSTEM,
      disk: { status: "degraded" as const, free_gb: 10, total_gb: 500, used_pct: 95 },
    });
    await renderWidget();
    expect(screen.getByText(/disk usage critical.*95/i)).toBeInTheDocument();
  });

  // ---- Security ban alert --------------------------------------------------

  it("shows banned IP alert when banned_count > 0", async () => {
    mockGetSecurity.mockResolvedValue({ ...HEALTHY_SECURITY, banned_count: 2 });
    await renderWidget();
    expect(screen.getByText(/2 ip\(s\) currently banned/i)).toBeInTheDocument();
  });

  // ---- Performance metrics -------------------------------------------------

  it("shows avg API latency from traffic stats", async () => {
    await renderWidget();
    // avg_latency_ms: 38 → "38 ms"
    expect(screen.getByText("38 ms")).toBeInTheDocument();
  });

  it("shows requests per second from traffic stats", async () => {
    await renderWidget();
    // requests_per_sec: 1.4 → "1.40"
    expect(screen.getByText("1.40")).toBeInTheDocument();
  });

  // ---- Security metrics ----------------------------------------------------

  it("shows tracked IPs count from security stats", async () => {
    await renderWidget();
    // total_ips: 3. Use getAllByText since "3" might appear in other places
    const matches = screen.getAllByText("3");
    expect(matches.length).toBeGreaterThan(0);
  });

  it("shows banned IPs count as 0 when no bans", async () => {
    await renderWidget();
    // banned_count: 0 appears in the security section
    const matches = screen.getAllByText("0");
    expect(matches.length).toBeGreaterThan(0);
  });

  // ---- Session section -----------------------------------------------------

  it("shows API connection status as 'connected'", async () => {
    await renderWidget();
    expect(screen.getByText("connected")).toBeInTheDocument();
  });

  it("shows WS connected as Yes when connected", async () => {
    await renderWidget();
    expect(screen.getByText("Yes")).toBeInTheDocument();
  });

  it("shows WS connected as No when disconnected", async () => {
    mockStoreState = { ...mockStoreState, wsConnected: false };
    await renderWidget();
    expect(screen.getByText("No")).toBeInTheDocument();
  });

  // ---- API calls -----------------------------------------------------------

  it("calls all four data sources on mount", async () => {
    await renderWidget();
    expect(mockPing).toHaveBeenCalledOnce();
    expect(mockGetHealth).toHaveBeenCalledOnce();
    expect(mockGetTraffic).toHaveBeenCalledOnce();
    expect(mockGetLatency).toHaveBeenCalledOnce();
    expect(mockGetSecurity).toHaveBeenCalledOnce();
  });

  // ---- Manual refresh ------------------------------------------------------

  it("re-calls all sources when refresh button is clicked", async () => {
    const user = userEvent.setup();
    await renderWidget();
    expect(mockPing).toHaveBeenCalledOnce();

    const btn = screen.getByRole("button", { name: /refresh/i });
    await act(async () => { await user.click(btn); });

    expect(mockPing).toHaveBeenCalledTimes(2);
  });

  // ---- Auto-refresh --------------------------------------------------------

  it("auto-refreshes after 30 seconds", async () => {
    vi.useFakeTimers();
    try {
      await act(async () => { render(<HealthWidget />); });
      // Flush initial async calls
      await act(async () => { await Promise.resolve(); });
      expect(mockPing).toHaveBeenCalledOnce();

      // Advance timer and flush the subsequent async chain
      await act(async () => { vi.advanceTimersByTime(30_000); });
      await act(async () => { await Promise.resolve(); });

      expect(mockPing).toHaveBeenCalledTimes(2);
    } finally {
      vi.useRealTimers();
    }
  });

  // ---- Error resilience ----------------------------------------------------

  it("does not crash when all API calls fail", async () => {
    mockPing.mockRejectedValue(new Error("network error"));
    mockGetHealth.mockRejectedValue(new Error("network error"));
    mockGetTraffic.mockRejectedValue(new Error("network error"));
    mockGetLatency.mockRejectedValue(new Error("network error"));
    mockGetSecurity.mockRejectedValue(new Error("network error"));

    await renderWidget();
    expect(screen.getByTestId("health-widget")).toBeInTheDocument();
  });

  it("shows alerts banner even when health API fails + WS is down", async () => {
    mockGetHealth.mockRejectedValue(new Error("network error"));
    mockStoreState = { ...mockStoreState, wsConnected: false };
    await renderWidget();
    expect(screen.getByText("WebSocket disconnected")).toBeInTheDocument();
  });

  it("shows '--' for latency values when traffic stats fail", async () => {
    mockGetTraffic.mockRejectedValue(new Error("fail"));
    await renderWidget();
    // Multiple "--" placeholders appear in the performance section
    const dashes = screen.getAllByText("--");
    expect(dashes.length).toBeGreaterThan(0);
  });

  it("does not show 'All systems operational' when WS is disconnected", async () => {
    mockStoreState = { ...mockStoreState, wsConnected: false };
    await renderWidget();
    expect(screen.queryByText(/all systems operational/i)).not.toBeInTheDocument();
  });
});
