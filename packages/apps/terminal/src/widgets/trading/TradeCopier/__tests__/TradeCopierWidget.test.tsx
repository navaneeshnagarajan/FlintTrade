import React, { createContext, useContext } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/components/ui/switch", () => ({
  Switch: ({
    checked,
    disabled,
    onCheckedChange,
    "aria-label": ariaLabel,
    "data-testid": testId,
  }: {
    checked: boolean;
    disabled?: boolean;
    onCheckedChange: (value: boolean) => void;
    "aria-label"?: string;
    "data-testid"?: string;
  }) => (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={ariaLabel}
      data-testid={testId}
      disabled={disabled}
      onClick={() => onCheckedChange(!checked)}
    />
  ),
}));

vi.mock("@/components/ui/select", () => {
  type SelectContext = {
    value?: string;
    disabled?: boolean;
    onValueChange?: (value: string) => void;
  };
  const Context = createContext<SelectContext>({});
  return {
    Select: ({
      value,
      disabled,
      onValueChange,
      children,
    }: SelectContext & { children?: React.ReactNode }) => (
      <Context.Provider value={{ value, disabled, onValueChange }}>{children}</Context.Provider>
    ),
    SelectTrigger: ({ children, ...props }: React.HTMLAttributes<HTMLSpanElement>) => (
      <span {...props}>{children}</span>
    ),
    SelectValue: ({ placeholder }: { placeholder?: string }) => <span>{placeholder}</span>,
    SelectContent: ({
      children,
      "data-testid": testId,
    }: {
      children?: React.ReactNode;
      "data-testid"?: string;
    }) => {
      const context = useContext(Context);
      return (
        <select
          data-testid={testId}
          value={context.value ?? ""}
          disabled={context.disabled}
          onChange={(event) => context.onValueChange?.(event.target.value)}
        >
          {children}
        </select>
      );
    },
    SelectItem: ({ value, children }: { value: string; children?: React.ReactNode }) => (
      <option value={value}>{children}</option>
    ),
  };
});

vi.mock("@/services/ftApi", () => ({
  getDittoAccounts: vi.fn(),
  getDittoMirrorStatus: vi.fn(),
  getDittoRisk: vi.fn(),
  setDittoAccountEnabled: vi.fn(),
  startDittoMirror: vi.fn(),
  stopDittoMirror: vi.fn(),
}));

import {
  getDittoAccounts,
  getDittoMirrorStatus,
  getDittoRisk,
  setDittoAccountEnabled,
  startDittoMirror,
  stopDittoMirror,
} from "@/services/ftApi";
import TradeCopierWidget from "../TradeCopierWidget";

const mockGetAccounts = vi.mocked(getDittoAccounts);
const mockGetStatus = vi.mocked(getDittoMirrorStatus);
const mockGetRisk = vi.mocked(getDittoRisk);
const mockSetEnabled = vi.mocked(setDittoAccountEnabled);
const mockStart = vi.mocked(startDittoMirror);
const mockStop = vi.mocked(stopDittoMirror);

const accounts = {
  accounts: [
    {
      id: "master",
      name: "Primary",
      broker: "OpenAlgo",
      capital: 0,
      pnl_today: 0,
      status: "active" as const,
      positions: 0,
      group: "personal",
      allocation_weight: 1,
      max_loss_daily: 50_000,
      is_master: true,
    },
    {
      id: "target",
      name: "Family",
      broker: "OpenAlgo",
      capital: 0,
      pnl_today: 0,
      status: "active" as const,
      positions: 0,
      group: "family",
      allocation_weight: 0.5,
      max_loss_daily: 25_000,
      is_master: false,
    },
    {
      id: "paused",
      name: "Paused account",
      broker: "OpenAlgo",
      capital: 0,
      pnl_today: 0,
      status: "disabled" as const,
      positions: 0,
      group: "family",
      allocation_weight: 1,
      max_loss_daily: 10_000,
      is_master: false,
    },
  ],
};

const stoppedStatus = {
  active: false,
  source_account: null,
  target_accounts: [],
  mode: "weighted" as const,
  mirrored_positions: 0,
  last_sync: null,
  errors: [],
};

function renderWidget() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: 0 },
      mutations: { retry: false },
    },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <TradeCopierWidget />
    </QueryClientProvider>,
  );
}

describe("TradeCopierWidget", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockGetAccounts.mockResolvedValue(accounts);
    mockGetStatus.mockResolvedValue(stoppedStatus);
    mockGetRisk.mockResolvedValue({
      complete: true,
      aggregate_capital: 800_000,
      aggregate_pnl: 2_500,
      accounts: [],
    });
    mockSetEnabled.mockResolvedValue(accounts.accounts[1]);
    mockStart.mockResolvedValue({
      active: true,
      source_account: "master",
      target_accounts: ["target"],
      mode: "weighted",
      started_at: "2026-07-14T10:00:00+05:30",
    });
    mockStop.mockResolvedValue({ active: false, stopped_at: "2026-07-14T10:01:00+05:30" });
  });

  it("renders canonical Ditto state without demo accounts or a simulated copy button", async () => {
    renderWidget();

    expect(screen.getByTestId("tradecopier-widget")).toBeInTheDocument();
    expect((await screen.findAllByText("Family")).length).toBeGreaterThanOrEqual(1);
    expect(screen.getByTestId("runtime-status")).toHaveTextContent("Stopped");
    expect(screen.queryByText(/demo accounts/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/test copy/i)).not.toBeInTheDocument();
    expect(screen.getByText("₹8,00,000")).toBeInTheDocument();
    expect(screen.getByText("₹2,500")).toBeInTheDocument();
  });

  it("prefers the configured master as source and lists real accounts", async () => {
    renderWidget();

    const select = await screen.findByTestId("source-select") as HTMLSelectElement;
    await waitFor(() => expect(select.value).toBe("master"));
    expect([...select.options].map((option) => option.value)).toEqual(["master", "target"]);
    expect(screen.getByText(/0.5x · daily loss limit ₹25,000/)).toBeInTheDocument();
  });

  it("starts the backend mirror with the selected target and allocation mode", async () => {
    renderWidget();

    const target = await screen.findByTestId("select-target-target");
    fireEvent.click(target);
    fireEvent.click(screen.getByTestId("mode-equal"));
    const start = screen.getByTestId("start-mirror");
    await waitFor(() => expect(start).toBeEnabled());
    fireEvent.click(start);

    // Arming a live multi-account mirror is confirmed first: the button opens
    // the dialog, and only the dialog's action arms it.
    expect(mockStart).not.toHaveBeenCalled();
    fireEvent.click(await screen.findByRole("button", { name: /^Start mirror$/ }));

    await waitFor(() => {
      expect(mockStart).toHaveBeenCalledWith("master", ["target"], "equal");
    });
  });

  it("uses the backend account lifecycle endpoint instead of changing local state only", async () => {
    renderWidget();

    fireEvent.click(await screen.findByTestId("enable-paused"));
    await waitFor(() => expect(mockSetEnabled).toHaveBeenCalledWith("paused", true));
  });

  it("reflects an active backend generation and stops it through the API", async () => {
    mockGetStatus.mockResolvedValue({
      active: true,
      source_account: "master",
      target_accounts: ["target"],
      mode: "weighted",
      mirrored_positions: 3,
      last_sync: "2026-07-14T10:00:00+05:30",
      errors: [],
    });
    renderWidget();

    const stop = await screen.findByTestId("stop-mirror");
    expect(screen.getByTestId("runtime-status")).toHaveTextContent("Running");
    expect(screen.getByTestId("mode-weighted")).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByText("3")).toBeInTheDocument();
    fireEvent.click(stop);

    await waitFor(() => expect(mockStop).toHaveBeenCalledOnce());
  });

  it("fails closed when runtime status cannot be read", async () => {
    mockGetStatus.mockRejectedValue(new Error("Ditto runtime unavailable"));
    renderWidget();

    expect(await screen.findByRole("alert", {}, { timeout: 3_000 })).toHaveTextContent("Ditto runtime unavailable");
    expect(screen.getByTestId("runtime-status")).toHaveTextContent("Unavailable");
    expect(screen.getByTestId("start-mirror")).toBeDisabled();
  });

  it("surfaces backend runtime errors without fabricating an event log", async () => {
    mockGetStatus.mockResolvedValue({
      ...stoppedStatus,
      errors: ["Target account could not be reconciled"],
    });
    renderWidget();

    expect(await screen.findByText("Target account could not be reconciled")).toBeInTheDocument();
    expect(screen.queryByText(/no copy events yet/i)).not.toBeInTheDocument();
  });

  it("shows an honest empty state when no accounts are configured", async () => {
    mockGetAccounts.mockResolvedValue({ accounts: [] });
    renderWidget();

    expect(await screen.findByText("No Ditto accounts configured")).toBeInTheDocument();
    expect(screen.getByTestId("start-mirror")).toBeDisabled();
  });
});
