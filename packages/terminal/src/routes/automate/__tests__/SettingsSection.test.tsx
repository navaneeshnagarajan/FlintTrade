/**
 * SettingsSection.test.tsx
 *
 * Tests for the Kill Switch / Safety Configuration / Telegram panel.
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

vi.mock("@/services/api", () => ({
  sendTelegram: vi.fn(),
}));

vi.mock("@/services/ftApi", () => ({
  getSafetyConfig: vi.fn().mockResolvedValue({
    kill_switch_active: false,
    max_positions: 10,
    max_margin_pct: 80,
    daily_loss_pause_pct: 3,
    daily_loss_kill_pct: 5,
    max_net_delta: 500,
    max_net_vega: 200,
  }),
  updateSafetyConfig: vi.fn(),
  activateKillSwitch: vi.fn(),
  resetKillSwitch: vi.fn(),
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

import SettingsSection from "../SettingsSection";

describe("SettingsSection", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("renders without crashing and shows Kill Switch heading", () => {
    render(<SettingsSection />, { wrapper: createWrapper() });
    expect(screen.getByText("Kill Switch")).toBeInTheDocument();
  });

  it("shows the Safety Configuration heading", () => {
    render(<SettingsSection />, { wrapper: createWrapper() });
    expect(screen.getByText("Safety Configuration")).toBeInTheDocument();
  });

  it("shows the Telegram Alerts heading", () => {
    render(<SettingsSection />, { wrapper: createWrapper() });
    expect(screen.getByText("Telegram Alerts")).toBeInTheDocument();
  });
});
