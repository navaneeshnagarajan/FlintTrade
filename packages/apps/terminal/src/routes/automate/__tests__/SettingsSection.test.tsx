/**
 * SettingsSection.test.tsx
 *
 * Tests for the Kill Switch / Safety Configuration / Telegram panel.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import "@testing-library/jest-dom";
import { onlineManager, QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React from "react";

const mockMode = vi.hoisted(() => ({ mode: "live" }));

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
    kill_switch_reason: "",
    flatten_complete: true,
    emergency_result: null,
  }),
  updateSafetyConfig: vi.fn(),
  activateKillSwitch: vi.fn(),
  resetKillSwitch: vi.fn(),
}));

vi.mock("@/stores/modeStore", () => ({
  useModeStore: vi.fn((selector: (state: { mode: string }) => unknown) =>
    selector({ mode: mockMode.mode }),
  ),
}));

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function createQueryClient() {
  return new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
}

function createWrapper(queryClient = createQueryClient()) {
  return ({ children }: { children: React.ReactNode }) =>
    React.createElement(QueryClientProvider, { client: queryClient }, children);
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((settle) => {
    resolve = settle;
  });
  return { promise, resolve };
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

import SettingsSection from "../SettingsSection";
import {
  activateKillSwitch,
  getSafetyConfig,
  resetKillSwitch,
  type SafetyConfig,
} from "@/services/ftApi";

const partialEmergencyResult = {
  policy: "l5_emergency_flatten",
  complete: false,
  target_count: 1,
  completed_target_count: 0,
  summary: "No configured targets completed",
  targets: [
    {
      selector: "configured:account",
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
  ],
  outcomes: [
    {
      verb: "cancel_all_orders",
      attempted: false,
      succeeded: false,
      failure_code: "router_unavailable",
    },
  ],
};

const inactiveSafetyConfig: SafetyConfig = {
  check_market_hours: true,
  max_qty_nse: 1800,
  max_qty_nfo: 1800,
  max_qty_mcx: 100,
  kill_switch_active: false,
  max_positions: 10,
  max_margin_pct: 80,
  daily_loss_pause_pct: 3,
  daily_loss_kill_pct: 5,
  max_net_delta: 500,
  max_net_vega: 200,
  kill_switch_reason: "",
  flatten_complete: true,
  emergency_result: null,
};

describe("SettingsSection", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockMode.mode = "live";
    vi.mocked(getSafetyConfig).mockReset().mockResolvedValue({ ...inactiveSafetyConfig });
    vi.mocked(activateKillSwitch).mockReset();
    vi.mocked(resetKillSwitch).mockReset();
  });

  afterEach(() => {
    onlineManager.setOnline(true);
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

  it("keeps emergency activation disabled while an offline query has no safety state", async () => {
    const user = userEvent.setup();
    onlineManager.setOnline(false);

    render(<SettingsSection />, { wrapper: createWrapper() });

    const button = screen.getByRole("button", { name: "Activate Kill Switch" });
    expect(button).toBeDisabled();
    await user.click(button);
    expect(activateKillSwitch).not.toHaveBeenCalled();
  });

  it("reports a latched kill switch when broker flattening is incomplete", async () => {
    const user = userEvent.setup();
    const activeConfig = {
      ...inactiveSafetyConfig,
      kill_switch_active: true,
      kill_switch_reason: "operator request",
      flatten_complete: false,
      emergency_result: partialEmergencyResult,
    };
    vi.mocked(getSafetyConfig)
      .mockResolvedValueOnce({ ...inactiveSafetyConfig })
      .mockResolvedValue(activeConfig);
    vi.mocked(activateKillSwitch).mockResolvedValueOnce({
      message: "Kill switch activated, but broker actions did not complete",
      reason: "operator request",
      is_active: true,
      emergency_actions: {
        ...partialEmergencyResult,
      },
    });
    render(<SettingsSection />, { wrapper: createWrapper() });

    await user.click(screen.getByRole("button", { name: "Activate Kill Switch" }));

    expect(
      await screen.findByText("Kill switch is active, but broker flattening is incomplete"),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retry Emergency Actions" })).toBeEnabled();
    expect(screen.queryByRole("button", { name: /reset kill switch/i })).not.toBeInTheDocument();
  });

  it("offers retry, but not reset, when durable flatten state is incomplete", async () => {
    const user = userEvent.setup();
    const activeConfig = {
      ...inactiveSafetyConfig,
      kill_switch_active: true,
      kill_switch_reason: "operator request",
      flatten_complete: false,
      emergency_result: partialEmergencyResult,
    };
    vi.mocked(getSafetyConfig)
      .mockResolvedValueOnce(activeConfig)
      .mockResolvedValue(activeConfig);
    vi.mocked(activateKillSwitch).mockResolvedValueOnce({
      message: "Kill switch remains active",
      reason: "operator request",
      is_active: true,
      emergency_actions: partialEmergencyResult,
    });
    render(<SettingsSection />, { wrapper: createWrapper() });

    await user.click(await screen.findByRole("button", { name: "Retry Emergency Actions" }));

    expect(activateKillSwitch).toHaveBeenCalledWith("operator request");
    expect(screen.getByText("No configured targets completed")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /reset kill switch/i })).not.toBeInTheDocument();
  });

  it("offers reset only after emergency flattening completed and refetches after reset", async () => {
    const user = userEvent.setup();
    const activeConfig = {
      ...inactiveSafetyConfig,
      kill_switch_active: true,
      kill_switch_reason: "operator request",
      flatten_complete: true,
      emergency_result: {
        ...partialEmergencyResult,
        complete: true,
        completed_target_count: 1,
        summary: "All configured targets completed",
        targets: [],
      },
    };
    vi.mocked(getSafetyConfig)
      .mockResolvedValueOnce(activeConfig)
      .mockResolvedValue({ ...inactiveSafetyConfig });
    vi.mocked(resetKillSwitch).mockResolvedValueOnce({ message: "Kill switch reset" });
    render(<SettingsSection />, { wrapper: createWrapper() });

    await user.click(await screen.findByRole("button", { name: /reset kill switch/i }));

    expect(await screen.findByRole("button", { name: "Activate Kill Switch" })).toBeEnabled();
    expect(getSafetyConfig).toHaveBeenCalledTimes(2);
    expect(screen.queryByRole("button", { name: "Retry Emergency Actions" })).not.toBeInTheDocument();
  });

  it("cancels a stale safety read and refetches after activation", async () => {
    const user = userEvent.setup();
    const staleRead = deferred<SafetyConfig>();
    const activeConfig: SafetyConfig = {
      ...inactiveSafetyConfig,
      kill_switch_active: true,
      kill_switch_reason: "operator request",
      flatten_complete: false,
      emergency_result: partialEmergencyResult,
    };
    const queryClient = createQueryClient();
    queryClient.setQueryData(["safetyConfig"], { ...inactiveSafetyConfig });
    vi.mocked(getSafetyConfig)
      .mockReturnValueOnce(staleRead.promise)
      .mockResolvedValue(activeConfig);
    vi.mocked(activateKillSwitch).mockResolvedValueOnce({
      message: "Kill switch activated, but broker actions did not complete",
      reason: "operator request",
      is_active: true,
      emergency_actions: partialEmergencyResult,
    });
    render(<SettingsSection />, { wrapper: createWrapper(queryClient) });

    await waitFor(() => expect(getSafetyConfig).toHaveBeenCalledTimes(1));
    await user.click(screen.getByRole("button", { name: "Activate Kill Switch" }));

    expect(
      await screen.findByText("Kill switch is active, but broker flattening is incomplete"),
    ).toBeInTheDocument();
    await waitFor(() => expect(getSafetyConfig).toHaveBeenCalledTimes(2));
    await act(async () => staleRead.resolve({ ...inactiveSafetyConfig }));

    expect(screen.getByRole("button", { name: "Retry Emergency Actions" })).toBeEnabled();
    expect(queryClient.getQueryData<SafetyConfig>(["safetyConfig"])?.kill_switch_active).toBe(true);
  });

  it("retains a successful activation if its query cache entry is removed in flight", async () => {
    const user = userEvent.setup();
    const activation = deferred<{
      message: string;
      reason: string;
      is_active: boolean;
      emergency_actions: typeof partialEmergencyResult;
    }>();
    const queryClient = createQueryClient();
    queryClient.setQueryData(["safetyConfig"], { ...inactiveSafetyConfig });
    vi.mocked(getSafetyConfig)
      .mockResolvedValueOnce({ ...inactiveSafetyConfig })
      .mockResolvedValue({
        ...inactiveSafetyConfig,
        kill_switch_active: true,
        kill_switch_reason: "operator request",
        flatten_complete: false,
        emergency_result: partialEmergencyResult,
      });
    vi.mocked(activateKillSwitch).mockReturnValueOnce(activation.promise);
    render(<SettingsSection />, { wrapper: createWrapper(queryClient) });

    await user.click(screen.getByRole("button", { name: "Activate Kill Switch" }));
    await waitFor(() => expect(activateKillSwitch).toHaveBeenCalledTimes(1));
    queryClient.removeQueries({ queryKey: ["safetyConfig"] });
    await act(async () => activation.resolve({
      message: "Kill switch activated, but broker actions did not complete",
      reason: "operator request",
      is_active: true,
      emergency_actions: partialEmergencyResult,
    }));

    await waitFor(() => {
      expect(queryClient.getQueryData<SafetyConfig>(["safetyConfig"])?.kill_switch_active).toBe(true);
    });
  });

  it("does not enable emergency controls outside Live mode", async () => {
    mockMode.mode = "practice";
    render(<SettingsSection />, { wrapper: createWrapper() });

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Activate Kill Switch" })).toBeDisabled();
    });
    expect(screen.getByText(/available only in Live mode/i)).toBeInTheDocument();
  });
});
