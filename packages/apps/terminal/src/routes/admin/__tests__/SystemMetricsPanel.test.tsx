/**
 * SystemMetricsPanel.test.tsx
 *
 * Tests for the /admin System Metrics panel.
 * Verifies loading state, successful render, and error state.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

const mockUseQuery = vi.fn();

vi.mock("@tanstack/react-query", () => ({
  useQuery: (...args: unknown[]) => mockUseQuery(...args),
}));

vi.mock("@/components/ui/button", () => ({
  Button: ({ children, onClick, disabled, ...rest }: {
    children: React.ReactNode;
    onClick?: () => void;
    disabled?: boolean;
    [key: string]: unknown;
  }) => (
    <button onClick={onClick} disabled={disabled} {...rest}>
      {children}
    </button>
  ),
}));

// ---------------------------------------------------------------------------
// Import component under test
// ---------------------------------------------------------------------------

import { SystemMetricsPanel } from "../SystemMetricsPanel";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const mockMetrics = {
  cpu_percent: 42.5,
  memory_percent: 67.3,
  memory_used_gb: 10.8,
  memory_total_gb: 16,
  disk_percent: 55.1,
  disk_used_gb: 275.5,
  disk_total_gb: 500,
  uptime_seconds: 172800, // 2 days
  network_io: {
    bytes_sent: 1_073_741_824,
    bytes_recv: 536_870_912,
    packets_sent: 12345,
    packets_recv: 67890,
  },
  process_count: 182,
  load_avg_1m: 1.2,
  load_avg_5m: 0.9,
  load_avg_15m: 0.7,
  collected_at: "2026-04-13T10:00:00Z",
};

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("SystemMetricsPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("shows loading state initially", () => {
    mockUseQuery.mockReturnValue({
      data: undefined,
      isLoading: true,
      isError: false,
      isFetching: true,
      dataUpdatedAt: 0,
      refetch: vi.fn(),
    });

    render(<SystemMetricsPanel />);
    expect(screen.getByText(/loading system metrics/i)).toBeInTheDocument();
  });

  it("shows error state when fetch fails", () => {
    mockUseQuery.mockReturnValue({
      data: undefined,
      isLoading: false,
      isError: true,
      isFetching: false,
      dataUpdatedAt: 0,
      refetch: vi.fn(),
    });

    render(<SystemMetricsPanel />);
    expect(screen.getByText(/failed to load system metrics/i)).toBeInTheDocument();
    expect(screen.getByText(/port 5100/i)).toBeInTheDocument();
  });

  it("renders CPU, memory, and disk usage bars when data is loaded", () => {
    mockUseQuery.mockReturnValue({
      data: mockMetrics,
      isLoading: false,
      isError: false,
      isFetching: false,
      dataUpdatedAt: Date.now(),
      refetch: vi.fn(),
    });

    render(<SystemMetricsPanel />);

    expect(screen.getByText("CPU")).toBeInTheDocument();
    expect(screen.getByText("Memory")).toBeInTheDocument();
    expect(screen.getByText("Disk")).toBeInTheDocument();
  });

  it("displays CPU percentage", () => {
    mockUseQuery.mockReturnValue({
      data: mockMetrics,
      isLoading: false,
      isError: false,
      isFetching: false,
      dataUpdatedAt: Date.now(),
      refetch: vi.fn(),
    });

    render(<SystemMetricsPanel />);
    expect(screen.getByText("42.5%")).toBeInTheDocument();
  });

  it("renders uptime stat card", () => {
    mockUseQuery.mockReturnValue({
      data: mockMetrics,
      isLoading: false,
      isError: false,
      isFetching: false,
      dataUpdatedAt: Date.now(),
      refetch: vi.fn(),
    });

    render(<SystemMetricsPanel />);
    // 2 days uptime — formatUptime(172800) = "2d 0m"
    expect(screen.getByText("2d 0m")).toBeInTheDocument();
    expect(screen.getByText(/uptime/i)).toBeInTheDocument();
  });

  it("displays network sent and received", () => {
    mockUseQuery.mockReturnValue({
      data: mockMetrics,
      isLoading: false,
      isError: false,
      isFetching: false,
      dataUpdatedAt: Date.now(),
      refetch: vi.fn(),
    });

    render(<SystemMetricsPanel />);
    expect(screen.getByText("Net Sent")).toBeInTheDocument();
    expect(screen.getByText("Net Recv")).toBeInTheDocument();
    // 1 GB sent
    expect(screen.getByText("1.0 GB")).toBeInTheDocument();
  });

  it("renders progress bars with correct aria attributes", () => {
    mockUseQuery.mockReturnValue({
      data: mockMetrics,
      isLoading: false,
      isError: false,
      isFetching: false,
      dataUpdatedAt: Date.now(),
      refetch: vi.fn(),
    });

    render(<SystemMetricsPanel />);
    const progressBars = screen.getAllByRole("progressbar");
    expect(progressBars.length).toBe(3); // CPU, Memory, Disk
  });

  it("renders refresh button", () => {
    mockUseQuery.mockReturnValue({
      data: mockMetrics,
      isLoading: false,
      isError: false,
      isFetching: false,
      dataUpdatedAt: Date.now(),
      refetch: vi.fn(),
    });

    render(<SystemMetricsPanel />);
    expect(screen.getByRole("button", { name: /refresh metrics now/i })).toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------
// formatUptime unit tests
// ---------------------------------------------------------------------------

describe("formatUptime", () => {
  // Re-implement the pure function to test it independently
  function formatUptime(seconds: number): string {
    const d = Math.floor(seconds / 86400);
    const h = Math.floor((seconds % 86400) / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    const parts: string[] = [];
    if (d > 0) parts.push(`${d}d`);
    if (h > 0) parts.push(`${h}h`);
    parts.push(`${m}m`);
    return parts.join(" ");
  }

  it("formats seconds-only uptime", () => {
    expect(formatUptime(45)).toBe("0m");
  });

  it("formats hours", () => {
    expect(formatUptime(3600)).toBe("1h 0m");
  });

  it("formats days + hours + minutes", () => {
    expect(formatUptime(2 * 86400 + 3 * 3600 + 15 * 60)).toBe("2d 3h 15m");
  });
});

describe("formatBytes", () => {
  function formatBytes(bytes: number): string {
    if (bytes >= 1_073_741_824) return `${(bytes / 1_073_741_824).toFixed(1)} GB`;
    if (bytes >= 1_048_576) return `${(bytes / 1_048_576).toFixed(1)} MB`;
    if (bytes >= 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${bytes} B`;
  }

  it("formats bytes", () => {
    expect(formatBytes(512)).toBe("512 B");
  });

  it("formats kilobytes", () => {
    expect(formatBytes(2048)).toBe("2.0 KB");
  });

  it("formats megabytes", () => {
    expect(formatBytes(5 * 1_048_576)).toBe("5.0 MB");
  });

  it("formats gigabytes", () => {
    expect(formatBytes(1_073_741_824)).toBe("1.0 GB");
  });
});
