/**
 * MonitoringSection — install-host resources must not be sample figures or 0/0.
 *
 * Explore sample disk/RAM and process RSS stay off the This host bars.
 * Missing CPU, GPU, and network rows say Unavailable.
 */

import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import "@testing-library/jest-dom";

import type { SystemHealth } from "@/services/ftApi.admin";

const api = vi.hoisted(() => ({
  getHealth: vi.fn(),
  getTrafficStats: vi.fn(),
  getLatencyStats: vi.fn(),
}));

vi.mock("@/services/ftApi", () => ({
  getHealth: api.getHealth,
  getTrafficStats: api.getTrafficStats,
  getLatencyStats: api.getLatencyStats,
}));

vi.mock("@/services/api", () => ({
  ping: vi.fn().mockRejectedValue(new Error("bridge offline")),
}));

vi.mock("@/stores/connectionStore", () => ({
  useConnectionStore: (
    selector: (state: { wsConnected: boolean; status: string; apiKey: string }) => unknown,
  ) => selector({ wsConnected: false, status: "disconnected", apiKey: "" }),
}));

vi.mock("@/hooks/useBrokerConnected", () => ({
  useDirectBrokerConnected: () => false,
}));

import { MonitoringSection } from "../MonitoringSection";

const traffic = {
  window_minutes: 15,
  total_requests: 0,
  requests_per_sec: 0,
  error_rate: 0,
  avg_latency_ms: 0,
  top_paths: [],
};

function renderSection() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  return render(<MonitoringSection />, { wrapper });
}

function health(overrides: Partial<SystemHealth> = {}): SystemHealth {
  return {
    status: "ok",
    broker: { status: "degraded", note: "Explore" },
    duckdb: { status: "ok" },
    disk: { status: "ok", scope: "host", free_gb: 40, total_gb: 100, used_gb: 60, used_pct: 60 },
    memory: {
      status: "ok",
      scope: "host",
      used_mb: 4096,
      total_mb: 16384,
      used_pct: 25,
      process: { scope: "process", rss_mb: 180, vms_mb: 900 },
    },
    cpu: { status: "ok", scope: "host", used_pct: 12.5, cores: 8 },
    gpu: {
      status: "ok",
      scope: "host",
      name: "Example GPU",
      used_mb: 512,
      total_mb: 8192,
      used_pct: 10,
    },
    network: {
      status: "ok",
      scope: "host",
      bytes_sent: 1.5 * (1024 ** 3),
      bytes_recv: 3 * (1024 ** 3),
    },
    ...overrides,
  };
}

describe("MonitoringSection host resources", () => {
  beforeEach(() => {
    api.getHealth.mockReset();
    api.getTrafficStats.mockReset();
    api.getLatencyStats.mockReset();
    api.getTrafficStats.mockResolvedValue(traffic);
    api.getLatencyStats.mockResolvedValue({});
  });

  it("paints install-host disk, RAM, CPU, GPU, and network", async () => {
    api.getHealth.mockResolvedValue(health());
    renderSection();

    const host = await screen.findByTestId("host-resources");
    expect(within(host).getAllByText("This host").length).toBeGreaterThan(0);
    expect(within(host).getByText("60.0 GB / 100 GB")).toBeInTheDocument();
    expect(within(host).getByText("4.0 GB / 16.0 GB")).toBeInTheDocument();
    expect(within(host).getByText("12.5% · 8 cores / 100%")).toBeInTheDocument();
    expect(within(host).getByText("GPU — Example GPU")).toBeInTheDocument();
    expect(within(host).getByText("Sent 1.5 GB · Received 3.0 GB")).toBeInTheDocument();
    expect(screen.getByTestId("process-resources")).toHaveTextContent("Process (this app)");
    expect(screen.getByTestId("process-resources")).toHaveTextContent("RSS 180 MB");
    expect(screen.getByTestId("process-resources")).toHaveTextContent("VMS 900 MB");

    const services = screen.getByTestId("subsystem-status");
    expect(within(services).getByText("Broker — Explore")).toBeInTheDocument();
    expect(within(services).getByText("DuckDB — Healthy")).toBeInTheDocument();
    expect(within(host).queryByText(/Broker/)).not.toBeInTheDocument();
  });

  it("labels process RSS as this app and does not fall back to 0/0 memory", async () => {
    api.getHealth.mockResolvedValue(health({
      memory: { status: "ok", rss_mb: 180, vms_mb: 900, percent: 1.2 },
      cpu: undefined,
      gpu: undefined,
      network: undefined,
    }));
    renderSection();

    const host = await screen.findByTestId("host-resources");
    expect(within(host).getByText("60.0 GB / 100 GB")).toBeInTheDocument();
    expect(within(host).getByText("Memory").parentElement).toHaveTextContent("Unavailable");
    expect(screen.queryByText("0 MB / 0 MB")).not.toBeInTheDocument();
    expect(screen.queryByText("0.0 GB / 0 GB")).not.toBeInTheDocument();
    expect(screen.getByTestId("process-resources")).toHaveTextContent("RSS 180 MB");
    expect(within(host).getAllByText("Unavailable").length).toBeGreaterThanOrEqual(3);
  });

  it("does not paint Explore sample figures as this host", async () => {
    api.getHealth.mockResolvedValue(health({
      disk: { status: "ok", scope: "sample", free_gb: 128, total_gb: 256, used_pct: 50 },
      memory: { status: "ok", scope: "sample", used_mb: 2048, total_mb: 8192, used_pct: 25 },
      cpu: undefined,
      gpu: undefined,
      network: undefined,
    }));
    renderSection();

    const host = await screen.findByTestId("host-resources");
    await waitFor(() => {
      expect(within(host).getByText("Disk").parentElement).toHaveTextContent("Unavailable");
    });
    expect(within(host).getByText("Memory").parentElement).toHaveTextContent("Unavailable");
    expect(within(host).queryByText(/256/)).not.toBeInTheDocument();
    expect(within(host).queryByText("8.0 GB")).not.toBeInTheDocument();
    expect(within(host).queryByText("2.0 GB")).not.toBeInTheDocument();
    expect(screen.queryByTestId("process-resources")).not.toBeInTheDocument();
  });

  it("fails closed when sample totals arrive without a host scope", async () => {
    api.getHealth.mockResolvedValue(health({
      disk: { status: "ok", free_gb: 128, total_gb: 256, used_pct: 50 },
      memory: { status: "ok", used_mb: 2048, total_mb: 8192, used_pct: 25 },
      cpu: undefined,
      gpu: undefined,
      network: undefined,
    }));
    renderSection();

    const host = await screen.findByTestId("host-resources");
    await waitFor(() => {
      expect(within(host).queryByText(/256/)).not.toBeInTheDocument();
    });
    expect(within(host).queryByText("8.0 GB")).not.toBeInTheDocument();
    expect(within(host).getByText("Disk").parentElement).toHaveTextContent("Unavailable");
    expect(within(host).getByText("Memory").parentElement).toHaveTextContent("Unavailable");
  });
});
