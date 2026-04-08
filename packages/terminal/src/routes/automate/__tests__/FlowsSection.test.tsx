/**
 * FlowsSection.test.tsx
 *
 * Tests for the Flow Builder tab — verifies heading, node palette stats,
 * and webhook list rendering.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
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

vi.mock("@/services/ftApi", () => ({
  getWebhooks: vi.fn().mockResolvedValue({ webhooks: [] }),
  createWebhook: vi.fn(),
  deleteWebhook: vi.fn(),
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

import FlowsSection from "../FlowsSection";

describe("FlowsSection", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("renders without crashing", () => {
    render(<FlowsSection />, { wrapper: createWrapper() });
    expect(screen.getByText("Flow Builder")).toBeInTheDocument();
  });

  it("displays node palette heading and node count stats", () => {
    render(<FlowsSection />, { wrapper: createWrapper() });
    expect(screen.getByText("Node Palette")).toBeInTheDocument();
    // The component renders 54 as the total node count
    expect(screen.getByText("54")).toBeInTheDocument();
  });

  it("shows the registered webhooks heading", () => {
    render(<FlowsSection />, { wrapper: createWrapper() });
    expect(screen.getByText("Registered Webhooks")).toBeInTheDocument();
  });

  it("shows the Create Webhook button", () => {
    render(<FlowsSection />, { wrapper: createWrapper() });
    expect(screen.getByText("Create Webhook")).toBeInTheDocument();
  });
});
