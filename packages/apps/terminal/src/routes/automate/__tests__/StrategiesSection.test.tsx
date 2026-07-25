/**
 * StrategiesSection.test.tsx
 *
 * Tests for the Python Strategies tab — verifies heading and stat counters.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
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
const mockStartUploadedStrategy = vi.fn().mockResolvedValue({ status: "started" });

vi.mock("@/services/ftApi", () => ({
  getUploadedStrategies: () => mockGetUploadedStrategies(),
  uploadStrategy: vi.fn(),
  startUploadedStrategy: (id: string) => mockStartUploadedStrategy(id),
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
    mockGetUploadedStrategies.mockReset().mockResolvedValue([]);
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

  it("renders a non-empty normalised uploaded-runner fixture", async () => {
    mockGetUploadedStrategies.mockResolvedValue([
      {
        id: "mean-reversion",
        name: "Mean Reversion",
        filename: "mean-reversion.py",
        status: "running",
        uploaded_at: "",
        started_at: null,
        error_message: null,
      },
    ]);
    render(<StrategiesSection />, { wrapper: createWrapper() });

    expect(await screen.findByText("Mean Reversion")).toBeInTheDocument();
    expect(screen.getByText("mean-reversion.py")).toBeInTheDocument();
    expect(screen.getAllByText("Running")).toHaveLength(2);
    expect(screen.getByRole("button", { name: "Stop Mean Reversion" })).toBeEnabled();
  });

  // Starting an uploaded strategy hands operator-supplied Python the order
  // path. It used to fire straight from the row button with no prompt, which
  // was a larger unconfirmed side effect than any other button in the app.
  it("confirms before starting a strategy, and does not start on cancel", async () => {
    mockGetUploadedStrategies.mockResolvedValue([
      {
        id: "breakout",
        name: "Breakout",
        filename: "breakout.py",
        status: "stopped",
        uploaded_at: "",
        started_at: null,
        error_message: null,
      },
    ]);
    render(<StrategiesSection />, { wrapper: createWrapper() });

    fireEvent.click(await screen.findByRole("button", { name: "Start Breakout" }));
    expect(mockStartUploadedStrategy).not.toHaveBeenCalled();

    // The dialog names the file, not just the display name — scoped to the
    // dialog because the table row shows the filename too.
    const dialog = await screen.findByRole("alertdialog");
    expect(dialog).toHaveTextContent("Start Breakout?");
    expect(dialog).toHaveTextContent("breakout.py");

    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(mockStartUploadedStrategy).not.toHaveBeenCalled());
  });

  it("starts the strategy once the confirmation is accepted", async () => {
    mockGetUploadedStrategies.mockResolvedValue([
      {
        id: "breakout",
        name: "Breakout",
        filename: "breakout.py",
        status: "stopped",
        uploaded_at: "",
        started_at: null,
        error_message: null,
      },
    ]);
    render(<StrategiesSection />, { wrapper: createWrapper() });

    fireEvent.click(await screen.findByRole("button", { name: "Start Breakout" }));
    fireEvent.click(await screen.findByRole("button", { name: "Start strategy" }));

    await waitFor(() => expect(mockStartUploadedStrategy).toHaveBeenCalledWith("breakout"));
  });
});
