import { dirname, resolve } from "node:path";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router";

// Mock framer-motion to avoid animation issues in tests
vi.mock("framer-motion", () => ({
  AnimatePresence: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  motion: {
    div: ({ children, ...props }: Record<string, unknown>) => (
      <div {...props}>{children as React.ReactNode}</div>
    ),
  },
}));

// Mock the motion config to avoid reduced-motion detection
vi.mock("@/lib/motion", () => ({
  motionConfig: {
    prefersReducedMotion: () => true,
    transitions: { tab: { duration: 0 } },
  },
}));

// Mock the ftApi module
vi.mock("@/services/ftApi", () => ({
  get: vi.fn(),
  getDittoAccounts: vi.fn(),
  addDittoAccount: vi.fn(),
  removeDittoAccount: vi.fn(),
  setDittoAccountEnabled: vi.fn(),
  getDittoMirrorStatus: vi.fn(),
  startDittoMirror: vi.fn(),
  stopDittoMirror: vi.fn(),
  getDittoRisk: vi.fn(),
  dittoKillAll: vi.fn(),
}));

vi.mock("@/services/gatewayApi", () => ({
  gatewayApi: {
    getRateLimits: vi.fn().mockResolvedValue({}),
    setRateLimit: vi.fn(),
  },
}));

vi.mock("@/services/ftApi.native", () => ({
  listBrokerRecommendations: vi.fn(),
}));

import DittoRoute from "../DittoRoute";
import {
  addDittoAccount,
  get,
  getDittoAccounts,
  getDittoMirrorStatus,
  getDittoRisk,
  dittoKillAll,
  removeDittoAccount,
  setDittoAccountEnabled,
} from "@/services/ftApi";
import { listBrokerRecommendations } from "@/services/ftApi.native";

const mockGet = get as unknown as ReturnType<typeof vi.fn>;
const mockGetAccounts = getDittoAccounts as ReturnType<typeof vi.fn>;
const mockAddAccount = addDittoAccount as ReturnType<typeof vi.fn>;
const mockRemoveAccount = removeDittoAccount as ReturnType<typeof vi.fn>;
const mockSetAccountEnabled = setDittoAccountEnabled as ReturnType<typeof vi.fn>;
const mockGetMirrorStatus = getDittoMirrorStatus as ReturnType<typeof vi.fn>;
const mockGetRisk = getDittoRisk as ReturnType<typeof vi.fn>;
const mockKillAll = dittoKillAll as ReturnType<typeof vi.fn>;
const mockListBrokerRecommendations = listBrokerRecommendations as unknown as ReturnType<typeof vi.fn>;

const testDir = dirname(fileURLToPath(import.meta.url));
const dittoRouteSource = () =>
  readFileSync(resolve(testDir, "../DittoRoute.tsx"), "utf8");

function createWrapper() {
  const qc = new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: 0 },
    },
  });
  return function Wrapper({ children }: { children: React.ReactNode }) {
    return (
      <QueryClientProvider client={qc}>
        <MemoryRouter>{children}</MemoryRouter>
      </QueryClientProvider>
    );
  };
}

const sampleAccounts = {
  accounts: [
    {
      id: "acc_1",
      name: "Client: Rajesh Mehta",
      broker: "Zerodha",
      capital: 5000000,
      pnl_today: 12500,
      status: "active" as const,
      positions: 8,
      group: "HNI",
      allocation_weight: 1.0,
      max_loss_daily: 50000,
      is_master: true,
    },
    {
      id: "acc_2",
      name: "Client: Priya Sharma",
      broker: "Dhan",
      capital: 3000000,
      pnl_today: -8200,
      status: "active" as const,
      positions: 5,
      group: "HNI",
      allocation_weight: 0.6,
      max_loss_daily: 50000,
      is_master: false,
    },
  ],
};

const sampleMirrorStatus = {
  active: false,
  source_account: null,
  target_accounts: [],
  mode: "weighted" as const,
  mirrored_positions: 0,
  last_sync: null,
  errors: [],
};

const sampleRisk = {
  complete: true,
  aggregate_pnl: 4300,
  aggregate_capital: 8000000,
  accounts: [
    {
      id: "acc_1",
      name: "Rajesh Mehta",
      margin_used_pct: 45.2,
      pnl_today: 12500,
      positions: 8,
      risk_status: "OK" as const,
      capital: 5000000,
    },
    {
      id: "acc_2",
      name: "Priya Sharma",
      margin_used_pct: 62.8,
      pnl_today: -8200,
      positions: 5,
      risk_status: "WARNING" as const,
      capital: 3000000,
    },
  ],
};

beforeEach(() => {
  vi.clearAllMocks();
  mockGet.mockImplementation((path: string) => {
    if (path === "accounts/status") {
      return Promise.resolve({
        accounts: [
          {
            account_id: "upstox-live-20260704",
            source: "native",
            broker: "upstox",
            broker_display: "Upstox",
            name: "Upstox live token test",
            enabled: true,
            connected: true,
            authenticated: true,
            needs_reauth: false,
            latency_ms: 0,
            error: "",
          },
        ],
        summary: { total: 1, connected: 1, authenticated: 1, needs_reauth: 0 },
      });
    }
    return Promise.resolve({});
  });
  mockListBrokerRecommendations.mockResolvedValue({ status: "success", use_cases: {} });
  mockGetAccounts.mockResolvedValue(sampleAccounts);
  mockAddAccount.mockResolvedValue(sampleAccounts.accounts[0]);
  mockRemoveAccount.mockResolvedValue({ id: "acc_2", removed: true });
  mockSetAccountEnabled.mockResolvedValue(sampleAccounts.accounts[0]);
  mockGetMirrorStatus.mockResolvedValue(sampleMirrorStatus);
  mockGetRisk.mockResolvedValue(sampleRisk);
  mockKillAll.mockResolvedValue({
    complete: true,
    cleanup_complete: true,
    message: "All managed accounts are flat",
    accounts_affected: 2,
    emergency_actions: {},
  });
});

describe("DittoRoute", () => {
  it("renders the Account Manager header", () => {
    render(<DittoRoute />, { wrapper: createWrapper() });
    expect(screen.getByText("Account Manager")).toBeInTheDocument();
  });

  it("keeps route-local checkmark SVG markup out of the source", () => {
    expect(dittoRouteSource()).not.toContain("<" + "svg");
  });

  it("renders all three tabs", () => {
    render(<DittoRoute />, { wrapper: createWrapper() });
    expect(screen.getByText("Accounts")).toBeInTheDocument();
    expect(screen.getByText("Position Mirror")).toBeInTheDocument();
    expect(screen.getByText("Risk Dashboard")).toBeInTheDocument();
  });

  it("shows accounts tab by default with table", async () => {
    render(<DittoRoute />, { wrapper: createWrapper() });
    await waitFor(() => {
      expect(screen.getByText("Managed Accounts")).toBeInTheDocument();
    });
    expect(screen.getByText("Client: Rajesh Mehta")).toBeInTheDocument();
    expect(screen.getByText("Client: Priya Sharma")).toBeInTheDocument();
  });

  it("keeps live broker status visible when there are no Ditto managed accounts", async () => {
    mockGetAccounts.mockResolvedValue({ accounts: [] });
    render(<DittoRoute />, { wrapper: createWrapper() });

    expect(await screen.findByText("Upstox live token test")).toBeInTheDocument();
    expect(screen.getByText(/Upstox · Native/i)).toBeInTheDocument();
    expect(screen.getByText("No accounts connected")).toBeInTheDocument();
  });

  it("shows Master badge on master account", async () => {
    render(<DittoRoute />, { wrapper: createWrapper() });
    await waitFor(() => {
      expect(screen.getByText("Master")).toBeInTheDocument();
    });
  });

  it("does not present unknown account metrics as zero when live risk is unavailable", async () => {
    mockGetRisk.mockRejectedValue(new Error("Risk snapshot unavailable"));
    render(<DittoRoute />, { wrapper: createWrapper() });

    expect(
      await screen.findByText(
        /Live capital, P&L, and position metrics are unavailable/,
        {},
        { timeout: 3_000 },
      ),
    ).toBeInTheDocument();
    expect(screen.getAllByText("Unavailable").length).toBeGreaterThan(0);
  });

  it("switches to Position Mirror tab on click", async () => {
    render(<DittoRoute />, { wrapper: createWrapper() });
    fireEvent.click(screen.getByText("Position Mirror"));
    await waitFor(() => {
      expect(screen.getByText(/Mirror Status/)).toBeInTheDocument();
    });
  });

  it("switches to Risk Dashboard tab on click", async () => {
    render(<DittoRoute />, { wrapper: createWrapper() });
    fireEvent.click(screen.getByText("Risk Dashboard"));
    await waitFor(() => {
      expect(screen.getByText("Kill All Positions")).toBeInTheDocument();
    });
  });

  it("displays aggregate P&L in risk tab", async () => {
    render(<DittoRoute />, { wrapper: createWrapper() });
    fireEvent.click(screen.getByText("Risk Dashboard"));
    await waitFor(() => {
      expect(screen.getByText("Aggregate P&L")).toBeInTheDocument();
    });
  });

  it("handles API error gracefully in accounts tab", async () => {
    mockGetAccounts.mockRejectedValue(new Error("Network error"));
    render(<DittoRoute />, { wrapper: createWrapper() });
    await waitFor(() => {
      expect(screen.getByText(/Could not load accounts/)).toBeInTheDocument();
    }, { timeout: 6000 });
  });

  it("opens Add Account and submits a managed account", async () => {
    render(<DittoRoute />, { wrapper: createWrapper() });
    await waitFor(() => {
      expect(screen.getByText("Managed Accounts")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: "Add Account" }));

    fireEvent.change(screen.getByLabelText("Account ID"), {
      target: { value: "family_01" },
    });
    fireEvent.change(screen.getByLabelText("OpenAlgo URL"), {
      target: { value: "http://127.0.0.1:5001" },
    });
    fireEvent.change(screen.getByLabelText("API Key"), {
      target: { value: "secret-key" },
    });
    fireEvent.change(screen.getByLabelText("Display Name"), {
      target: { value: "Family Account" },
    });
    fireEvent.change(screen.getByLabelText("Group"), {
      target: { value: "Family" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save Account" }));

    await waitFor(() => {
      expect(mockAddAccount).toHaveBeenCalledWith({
        account_id: "family_01",
        openalgo_host: "http://127.0.0.1:5001",
        api_key: "secret-key",
        name: "Family Account",
        group: "Family",
        allocation_weight: 1,
        max_loss_daily: 50000,
        enabled: true,
        is_master: false,
      });
    });
  });

  it("enables, disables, and removes managed accounts", async () => {
    render(<DittoRoute />, { wrapper: createWrapper() });
    await waitFor(() => {
      expect(screen.getByText("Client: Rajesh Mehta")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: "Disconnect Client: Rajesh Mehta" }));
    await waitFor(() => {
      expect(mockSetAccountEnabled).toHaveBeenCalledWith("acc_1", false);
    });

    fireEvent.click(screen.getByRole("button", { name: "Remove Client: Priya Sharma" }));
    await waitFor(() => {
      expect(mockRemoveAccount).toHaveBeenCalledWith("acc_2");
    });
  });

  it("shows Start Position Mirroring button in mirror tab", async () => {
    render(<DittoRoute />, { wrapper: createWrapper() });
    fireEvent.click(screen.getByText("Position Mirror"));
    await waitFor(() => {
      expect(screen.getByText("Start Position Mirroring")).toBeInTheDocument();
    });
    expect(dittoRouteSource()).toContain("Copy 1:1 (full quantity to each target)");
    expect(dittoRouteSource()).toContain("By allocation weight (split quantity)");
  });

  it("hydrates and locks configuration while a mirror generation is active", async () => {
    mockGetMirrorStatus.mockResolvedValue({
      active: true,
      source_account: "acc_1",
      target_accounts: ["acc_2"],
      mode: "equal",
      mirrored_positions: 4,
      last_sync: "2026-07-14T10:00:00+05:30",
      errors: [],
    });
    render(<DittoRoute />, { wrapper: createWrapper() });
    fireEvent.click(screen.getByText("Position Mirror"));

    expect(await screen.findByText("Mirror Status: Active")).toBeInTheDocument();
    const comboboxes = screen.getAllByRole("combobox");
    expect(comboboxes).toHaveLength(2);
    comboboxes.forEach((control) => expect(control).toBeDisabled());
    expect(screen.getByRole("button", { name: /Client: Priya Sharma/ })).toBeDisabled();
    expect(screen.queryByText("Start Position Mirroring")).not.toBeInTheDocument();
  });

  it("renders risk failure as unavailable instead of zero exposure", async () => {
    mockGetRisk.mockRejectedValue(new Error("Risk snapshot unavailable"));
    render(<DittoRoute />, { wrapper: createWrapper() });
    fireEvent.click(screen.getByText("Risk Dashboard"));

    expect(await screen.findByRole("alert", {}, { timeout: 3_000 })).toHaveTextContent(
      "Risk snapshot unavailable",
    );
    expect(screen.queryByText("₹0")).not.toBeInTheDocument();
  });

  it("keeps the kill confirmation open and reports an incomplete flatten", async () => {
    mockKillAll.mockRejectedValue(new Error("One or more managed accounts could not be fully flattened"));
    render(<DittoRoute />, { wrapper: createWrapper() });
    fireEvent.click(screen.getByText("Risk Dashboard"));
    fireEvent.click(await screen.findByText("Kill All Positions"));
    fireEvent.click(screen.getByText("Confirm Kill All"));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "One or more managed accounts could not be fully flattened",
    );
    expect(screen.getByText("Confirm Kill All")).toBeInTheDocument();
  });
});
