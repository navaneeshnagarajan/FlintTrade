/**
 * LogsSection.test.tsx
 *
 * Execution Logs (FT-AUTO-003) — Explore empty ≠ outage, Practice/Live
 * empty range, real load failure, and loading must not flash the outage copy.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import "@testing-library/jest-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React from "react";

const mockMode = vi.hoisted(() => ({ mode: "explore" }));
const mockGetAuditLogs = vi.hoisted(() =>
  vi.fn().mockResolvedValue({ logs: [], total: 0 }),
);

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

vi.mock("framer-motion", () => ({
  motion: {
    div: ({ children, ...props }: React.HTMLAttributes<HTMLDivElement>) => (
      <div {...props}>{children}</div>
    ),
  },
  AnimatePresence: ({ children }: { children: React.ReactNode }) => (
    <>{children}</>
  ),
}));

vi.mock("@/components/ui/GlassCard", () => ({
  GlassCard: ({ children, ...props }: React.HTMLAttributes<HTMLDivElement>) => (
    <div {...props}>{children}</div>
  ),
  default: ({ children, ...props }: React.HTMLAttributes<HTMLDivElement>) => (
    <div {...props}>{children}</div>
  ),
}));

vi.mock("@/services/ftApi", () => ({
  getAuditLogs: (...args: unknown[]) => mockGetAuditLogs(...args),
}));

vi.mock("@/stores/modeStore", () => ({
  useModeStore: vi.fn((selector: (state: { mode: string }) => unknown) =>
    selector({ mode: mockMode.mode }),
  ),
}));

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const EXPLORE_EMPTY =
  "No execution logs in Explore (sample-only). Switch to Practice or Live to see real run history.";
const DATE_EMPTY = "No execution logs for this date.";
const LOAD_ERROR = "Failed to load logs. Backend may be offline.";
const LOADING = "Loading logs…";

function createWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return ({ children }: { children: React.ReactNode }) =>
    React.createElement(QueryClientProvider, { client: queryClient }, children);
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((settle, fail) => {
    resolve = settle;
    reject = fail;
  });
  return { promise, resolve, reject };
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

import LogsSection from "../LogsSection";

describe("LogsSection", () => {
  beforeEach(() => {
    mockMode.mode = "explore";
    mockGetAuditLogs.mockReset();
    mockGetAuditLogs.mockResolvedValue({ logs: [], total: 0 });
  });

  it("renders without crashing and shows heading", () => {
    render(<LogsSection />, { wrapper: createWrapper() });
    expect(screen.getByText("Execution Logs")).toBeInTheDocument();
  });

  it("shows audit-trail description", () => {
    render(<LogsSection />, { wrapper: createWrapper() });
    expect(
      screen.getByText(/Append-only audit trail/),
    ).toBeInTheDocument();
  });

  it("shows muted Explore empty copy and never the outage line on a healthy sample session", async () => {
    mockMode.mode = "explore";
    mockGetAuditLogs.mockRejectedValue(new Error("backend offline"));

    render(<LogsSection />, { wrapper: createWrapper() });

    expect(await screen.findByText(EXPLORE_EMPTY)).toBeInTheDocument();
    expect(screen.queryByText(LOAD_ERROR)).not.toBeInTheDocument();
    expect(screen.queryByText(DATE_EMPTY)).not.toBeInTheDocument();
    expect(screen.queryByRole("columnheader", { name: "Time" })).not.toBeInTheDocument();
    expect(mockGetAuditLogs).not.toHaveBeenCalled();
  });

  it("shows the date-empty copy for a Practice 200 OK with 0 rows, not an outage", async () => {
    mockMode.mode = "practice";
    mockGetAuditLogs.mockResolvedValue({ logs: [], total: 0 });

    render(<LogsSection />, { wrapper: createWrapper() });

    expect(await screen.findByText(DATE_EMPTY)).toBeInTheDocument();
    expect(screen.queryByText(LOAD_ERROR)).not.toBeInTheDocument();
    expect(screen.queryByText(EXPLORE_EMPTY)).not.toBeInTheDocument();
  });

  it("shows the date-empty copy for a Live 200 OK with 0 rows, not an outage", async () => {
    mockMode.mode = "live";
    mockGetAuditLogs.mockResolvedValue({ logs: [], total: 0 });

    render(<LogsSection />, { wrapper: createWrapper() });

    expect(await screen.findByText(DATE_EMPTY)).toBeInTheDocument();
    expect(screen.queryByText(LOAD_ERROR)).not.toBeInTheDocument();
    expect(screen.queryByText(EXPLORE_EMPTY)).not.toBeInTheDocument();
  });

  it("shows the outage copy only when a Practice/Live request actually fails", async () => {
    mockMode.mode = "practice";
    mockGetAuditLogs.mockRejectedValue(new Error("backend offline"));

    render(<LogsSection />, { wrapper: createWrapper() });

    expect(await screen.findByText(LOAD_ERROR)).toBeInTheDocument();
    expect(screen.queryByText(DATE_EMPTY)).not.toBeInTheDocument();
    expect(screen.queryByText(EXPLORE_EMPTY)).not.toBeInTheDocument();
  });

  it("shows loading copy while the request is in flight and never flashes the outage line", async () => {
    mockMode.mode = "practice";
    const pending = deferred<{ logs: unknown[]; total: number }>();
    mockGetAuditLogs.mockReturnValue(pending.promise);

    render(<LogsSection />, { wrapper: createWrapper() });

    expect(await screen.findByText(LOADING)).toBeInTheDocument();
    expect(screen.queryByText(LOAD_ERROR)).not.toBeInTheDocument();
    expect(screen.queryByText(DATE_EMPTY)).not.toBeInTheDocument();

    pending.resolve({ logs: [], total: 0 });

    expect(await screen.findByText(DATE_EMPTY)).toBeInTheDocument();
    expect(screen.queryByText(LOAD_ERROR)).not.toBeInTheDocument();
    expect(screen.queryByText(LOADING)).not.toBeInTheDocument();
  });

  it("retries a failed Practice load from the error state", async () => {
    mockMode.mode = "practice";
    mockGetAuditLogs
      .mockRejectedValueOnce(new Error("backend offline"))
      .mockResolvedValueOnce({ logs: [], total: 0 });

    render(<LogsSection />, { wrapper: createWrapper() });

    expect(await screen.findByText(LOAD_ERROR)).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: /retry/i }));

    await waitFor(() => {
      expect(screen.getByText(DATE_EMPTY)).toBeInTheDocument();
    });
    expect(screen.queryByText(LOAD_ERROR)).not.toBeInTheDocument();
    expect(mockGetAuditLogs).toHaveBeenCalledTimes(2);
  });
});
