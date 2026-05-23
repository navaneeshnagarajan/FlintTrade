/**
 * LogsSection.test.tsx
 *
 * Tests for the Execution Logs tab — verifies heading and empty state.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React from "react";

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

const mockGetAuditLogs = vi.fn().mockResolvedValue({ logs: [], total: 0 });

vi.mock("@/services/ftApi", () => ({
  getAuditLogs: (...args: unknown[]) => mockGetAuditLogs(...args),
}));

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function createWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return ({ children }: { children: React.ReactNode }) =>
    React.createElement(QueryClientProvider, { client: queryClient }, children);
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

import LogsSection from "../LogsSection";

describe("LogsSection", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("renders without crashing and shows heading", () => {
    render(<LogsSection />, { wrapper: createWrapper() });
    expect(screen.getByText("Execution Logs")).toBeInTheDocument();
  });

  it("shows SEBI-compliance description", () => {
    render(<LogsSection />, { wrapper: createWrapper() });
    expect(
      screen.getByText(/SEBI-compliant audit trail/),
    ).toBeInTheDocument();
  });

  it("shows empty state when no logs exist for the date", async () => {
    mockGetAuditLogs.mockResolvedValue({ logs: [], total: 0 });
    render(<LogsSection />, { wrapper: createWrapper() });

    await waitFor(() => {
      expect(screen.getByText(/No logs for/)).toBeInTheDocument();
    });
  });
});
