/**
 * ObservabilityDashboard.test.tsx
 *
 * Verifies the /admin/observability aggregator:
 *   (a) the route path "/admin/observability" resolves to a component;
 *   (b) ObservabilityDashboard renders and every composed observability surface
 *       mounts without throwing.
 *
 * The composed surfaces source their data through @/services/ftApi and
 * @tanstack/react-query; both are mocked here exactly as the neighbouring widget
 * tests do, so the dashboard mounts in isolation without a live backend.
 */

import { describe, it, expect, vi, beforeAll } from "vitest";
import { render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";

// ---------------------------------------------------------------------------
// Mocks — factories must not reference outer variables (Vitest hoisting rule)
// ---------------------------------------------------------------------------

// ResizeObserver is referenced by chart-bearing children; provide a no-op shim.
beforeAll(() => {
  global.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
  global.URL.createObjectURL = vi.fn().mockReturnValue("blob:mock");
  global.URL.revokeObjectURL = vi.fn();
});

// HealthWidget pings OpenAlgo on mount.
vi.mock("@/services/api", () => ({
  ping: vi.fn().mockResolvedValue({ status: "ok" }),
}));

// The shared admin/data client used by every composed surface.
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
    total_requests: 0,
    requests_per_sec: 0,
    error_rate: 0,
    avg_latency_ms: 0,
    top_paths: [],
  }),
  getLatencyStats: vi.fn().mockResolvedValue({}),
  getSecurityStats: vi.fn().mockResolvedValue({ total_ips: 0, banned_count: 0, top_offenders: [] }),
  getBannedIPs: vi.fn().mockResolvedValue({ bans: [] }),
  getSecuritySettings: vi.fn().mockResolvedValue({
    auto_ban_enabled: false,
    ban_threshold: 25,
    notfound_ban_threshold: 10,
    ban_duration: 24,
  }),
  banIP: vi.fn().mockResolvedValue({ status: "ok" }),
  unbanIP: vi.fn().mockResolvedValue({ status: "ok" }),
  updateSecuritySettings: vi.fn().mockResolvedValue({ status: "ok" }),
  getActivityLog: vi.fn().mockResolvedValue({ entries: [], total: 0 }),
}));

// Zustand connection store consumed by HealthWidget.
vi.mock("@/stores/connectionStore", () => ({
  useConnectionStore: () => ({ status: "connected", wsConnected: true, lastPing: Date.now() }),
}));

// auth store consulted by SystemMetricsPanel (demo gating).
vi.mock("@/stores/authStore", () => ({
  useAuthStore: { getState: () => ({ token: "live-session" }) },
}));

// Hooks consumed by AuditTrailWidget.
vi.mock("@/hooks/useTrackBehavior", () => ({
  useTrackBehavior: () => vi.fn(),
}));
vi.mock("@/hooks/useBrokerConnected", () => ({
  useBrokerConnected: vi.fn().mockReturnValue(false),
  useDirectBrokerConnected: vi.fn().mockReturnValue(false),
}));

// react-query: panels read data through useQuery. Return a stable, non-loading
// empty result so each panel renders its empty/error branch without throwing.
// Mutations (SecuritySection) get inert handlers.
vi.mock("@tanstack/react-query", () => ({
  useQuery: () => ({
    data: undefined,
    isLoading: false,
    isError: true,
    isFetching: false,
    isSuccess: false,
    dataUpdatedAt: 0,
    refetch: vi.fn(),
  }),
  useMutation: () => ({ mutate: vi.fn(), isPending: false, isError: false, reset: vi.fn() }),
  useQueryClient: () => ({ invalidateQueries: vi.fn() }),
}));

// ---------------------------------------------------------------------------
// Import after mocks
// ---------------------------------------------------------------------------

import ObservabilityDashboard, { ObservabilityDashboard as NamedDashboard } from "../ObservabilityDashboard";

// ---------------------------------------------------------------------------
// (a) Route resolves to a component
// ---------------------------------------------------------------------------

describe("admin/observability route registration", () => {
  it("lazy-loads the dashboard module to a renderable component", async () => {
    const mod = await import("../index");
    expect(typeof mod.default).toBe("function");
    expect(mod.ObservabilityDashboard).toBe(NamedDashboard);
  });
});

// ---------------------------------------------------------------------------
// (b) Dashboard renders + all composed surfaces mount
// ---------------------------------------------------------------------------

describe("ObservabilityDashboard", () => {
  it("renders the page heading", () => {
    render(<ObservabilityDashboard />);
    expect(screen.getByRole("heading", { level: 1, name: "Observability" })).toBeInTheDocument();
  });

  it("renders all five composed observability section headings", () => {
    render(<ObservabilityDashboard />);
    expect(screen.getByRole("heading", { name: "System Health" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "System Metrics" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Traffic & Latency" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Security & Rate Limiting" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Audit Trail" })).toBeInTheDocument();
  });

  it("mounts each section landmark without throwing", () => {
    render(<ObservabilityDashboard />);
    for (const title of [
      "System Health",
      "System Metrics",
      "Traffic & Latency",
      "Security & Rate Limiting",
      "Audit Trail",
    ]) {
      expect(screen.getByRole("region", { name: title })).toBeInTheDocument();
    }
  });

  it("mounts the HealthWidget child surface", () => {
    render(<ObservabilityDashboard />);
    expect(screen.getByTestId("health-widget")).toBeInTheDocument();
  });

  it("uses British-English copy in the page description", () => {
    render(<ObservabilityDashboard />);
    expect(screen.getByText(/visualisation of platform health/i)).toBeInTheDocument();
  });
});
