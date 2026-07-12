/**
 * SettingsSection.test.tsx
 *
 * Tests for the Kill Switch / Safety Configuration / Telegram panel.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
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
import { activateKillSwitch } from "@/services/ftApi";

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

  it("reports a latched kill switch when broker flattening is incomplete", async () => {
    const user = userEvent.setup();
    vi.mocked(activateKillSwitch).mockResolvedValueOnce({
      message: "Kill switch activated, but broker actions did not complete",
      reason: "operator request",
      is_active: true,
      emergency_actions: {
        policy: "l5_emergency_flatten",
        complete: false,
        outcomes: [
          {
            verb: "cancel_all_orders",
            attempted: false,
            succeeded: false,
            failure_code: "router_unavailable",
          },
        ],
      },
    });
    render(<SettingsSection />, { wrapper: createWrapper() });

    await user.click(screen.getByRole("button", { name: "Activate Kill Switch" }));

    expect(
      await screen.findByText("Kill switch is active, but broker flattening is incomplete"),
    ).toBeInTheDocument();
  });
});
