/**
 * MonitorsSection.test.tsx
 *
 * Tests for the Live Strategy Monitors tab — verifies heading and empty state.
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

vi.mock("@/components/motion/StaggeredList", () => ({
  StaggeredList: ({ children, ...props }: React.HTMLAttributes<HTMLDivElement>) => (
    <div {...props}>{children}</div>
  ),
  default: ({ children, ...props }: React.HTMLAttributes<HTMLDivElement>) => (
    <div {...props}>{children}</div>
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

const mockGetRunningStrategies = vi.fn().mockResolvedValue([]);

vi.mock("@/services/ftApi", () => ({
  getRunningStrategies: () => mockGetRunningStrategies(),
  stopStrategy: vi.fn(),
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

import MonitorsSection from "../MonitorsSection";

describe("MonitorsSection", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("renders without crashing and shows heading", () => {
    render(<MonitorsSection />, { wrapper: createWrapper() });
    expect(screen.getByText("Live Strategy Monitors")).toBeInTheDocument();
  });

  it("shows empty state when no strategies are running", async () => {
    mockGetRunningStrategies.mockResolvedValue([]);
    render(<MonitorsSection />, { wrapper: createWrapper() });

    await waitFor(() => {
      expect(screen.getByText("No strategies running")).toBeInTheDocument();
    });
  });
});
