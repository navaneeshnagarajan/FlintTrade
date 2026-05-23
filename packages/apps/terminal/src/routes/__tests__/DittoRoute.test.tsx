import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";

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
  getDittoAccounts: vi.fn(),
  getDittoMirrorStatus: vi.fn(),
  startDittoMirror: vi.fn(),
  stopDittoMirror: vi.fn(),
  getDittoRisk: vi.fn(),
  dittoKillAll: vi.fn(),
}));

import DittoRoute from "../DittoRoute";
import {
  getDittoAccounts,
  getDittoMirrorStatus,
  getDittoRisk,
} from "@/services/ftApi";

const mockGetAccounts = getDittoAccounts as ReturnType<typeof vi.fn>;
const mockGetMirrorStatus = getDittoMirrorStatus as ReturnType<typeof vi.fn>;
const mockGetRisk = getDittoRisk as ReturnType<typeof vi.fn>;

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
      is_master: false,
    },
  ],
};

const sampleMirrorStatus = {
  active: false,
  source_account: null,
  target_accounts: [],
  mode: "proportional" as const,
  mirrored_positions: 0,
  last_sync: null,
  errors: [],
};

const sampleRisk = {
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
    },
    {
      id: "acc_2",
      name: "Priya Sharma",
      margin_used_pct: 62.8,
      pnl_today: -8200,
      positions: 5,
      risk_status: "WARNING" as const,
    },
  ],
};

beforeEach(() => {
  vi.clearAllMocks();
  mockGetAccounts.mockResolvedValue(sampleAccounts);
  mockGetMirrorStatus.mockResolvedValue(sampleMirrorStatus);
  mockGetRisk.mockResolvedValue(sampleRisk);
});

describe("DittoRoute", () => {
  it("renders the Multi-Account Manager header", () => {
    render(<DittoRoute />, { wrapper: createWrapper() });
    expect(screen.getByText("Multi-Account Manager")).toBeInTheDocument();
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

  it("shows Master badge on master account", async () => {
    render(<DittoRoute />, { wrapper: createWrapper() });
    await waitFor(() => {
      expect(screen.getByText("Master")).toBeInTheDocument();
    });
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

  it("shows Add Account button (disabled)", async () => {
    render(<DittoRoute />, { wrapper: createWrapper() });
    await waitFor(() => {
      const addButton = screen.getByText("Add Account");
      expect(addButton).toBeInTheDocument();
      expect(addButton.closest("button")).toBeDisabled();
    });
  });

  it("shows Start Position Mirroring button in mirror tab", async () => {
    render(<DittoRoute />, { wrapper: createWrapper() });
    fireEvent.click(screen.getByText("Position Mirror"));
    await waitFor(() => {
      expect(screen.getByText("Start Position Mirroring")).toBeInTheDocument();
    });
  });
});
