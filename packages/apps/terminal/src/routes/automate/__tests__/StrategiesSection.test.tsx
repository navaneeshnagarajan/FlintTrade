/**
 * StrategiesSection.test.tsx
 *
 * Tests for the Python Strategies tab — verifies heading and stat counters.
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

vi.mock("@/components/ui/scroll-area", () => ({
  ScrollArea: ({ children, ...props }: React.HTMLAttributes<HTMLDivElement>) => (
    <div {...props}>{children}</div>
  ),
}));

const mockGetUploadedStrategies = vi.fn().mockResolvedValue([]);

vi.mock("@/services/ftApi", () => ({
  getUploadedStrategies: () => mockGetUploadedStrategies(),
  uploadStrategy: vi.fn(),
  startUploadedStrategy: vi.fn(),
  stopUploadedStrategy: vi.fn(),
  getStrategyLogs: vi.fn().mockResolvedValue([]),
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

import StrategiesSection from "../StrategiesSection";

describe("StrategiesSection", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("renders without crashing and shows heading", () => {
    render(<StrategiesSection />, { wrapper: createWrapper() });
    expect(screen.getByText("Python Strategies")).toBeInTheDocument();
  });

  it("shows the Upload Strategy button", () => {
    render(<StrategiesSection />, { wrapper: createWrapper() });
    expect(screen.getByText("Upload Strategy")).toBeInTheDocument();
  });

  it("shows empty state when no strategies exist", async () => {
    mockGetUploadedStrategies.mockResolvedValue([]);
    render(<StrategiesSection />, { wrapper: createWrapper() });

    await waitFor(() => {
      expect(screen.getByText("No strategies uploaded yet.")).toBeInTheDocument();
    });
  });
});
