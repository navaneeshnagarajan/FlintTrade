/**
 * AuditTrailWidget.test.tsx
 *
 * Tests: render, table headers, sample data (explore), filters, CSV export
 * button, and the honest connected-mode behaviour (no fabricated rows; honest
 * empty state on an empty live response).
 */

import { describe, it, expect, vi, beforeAll, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import "@testing-library/jest-dom";

beforeAll(() => {
  global.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };

  // Mock URL.createObjectURL / revokeObjectURL for CSV export
  global.URL.createObjectURL = vi.fn().mockReturnValue("blob:mock");
  global.URL.revokeObjectURL = vi.fn();
});

vi.mock("@/hooks/useTrackBehavior", () => ({
  useTrackBehavior: () => vi.fn(),
}));

vi.mock("@/hooks/useBrokerConnected", () => ({
  useBrokerConnected: vi.fn().mockReturnValue(false),
}));

vi.mock("@/services/ftApi", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/services/ftApi")>();
  return { ...actual, getActivityLog: vi.fn() };
});

import { useBrokerConnected } from "@/hooks/useBrokerConnected";
import { getActivityLog } from "@/services/ftApi";
import AuditTrailWidget from "../AuditTrailWidget";

const mockConnected = useBrokerConnected as ReturnType<typeof vi.fn>;
const mockActivityLog = getActivityLog as ReturnType<typeof vi.fn>;

function wrapper({ children }: { children: ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

beforeEach(() => {
  mockConnected.mockReturnValue(false);
  mockActivityLog.mockReset();
  mockActivityLog.mockResolvedValue({ entries: [], total: 0 });
});

describe("AuditTrailWidget", () => {
  it("renders the widget header", () => {
    render(<AuditTrailWidget />, { wrapper });
    expect(screen.getByText("Audit Trail")).toBeTruthy();
  });

  it("renders audit-log badge", () => {
    render(<AuditTrailWidget />, { wrapper });
    expect(screen.getByText("Audit log")).toBeTruthy();
  });

  it("renders table column headers", () => {
    render(<AuditTrailWidget />, { wrapper });
    expect(screen.getByText("Timestamp (IST)")).toBeTruthy();
    expect(screen.getByText("Action")).toBeTruthy();
    expect(screen.getByText("Details")).toBeTruthy();
    expect(screen.getByText("User")).toBeTruthy();
    expect(screen.getByText("IP")).toBeTruthy();
  });

  it("renders sample audit entries when disconnected", () => {
    mockConnected.mockReturnValue(false);
    render(<AuditTrailWidget />, { wrapper });
    expect(screen.getByText(/BUY NIFTY 22500 CE/)).toBeTruthy();
  });

  it("shows the Sample data affordance when disconnected", () => {
    mockConnected.mockReturnValue(false);
    render(<AuditTrailWidget />, { wrapper });
    expect(screen.getByText("Sample data")).toBeTruthy();
  });

  it("shows entry count in filter bar", () => {
    mockConnected.mockReturnValue(false);
    render(<AuditTrailWidget />, { wrapper });
    expect(screen.getByText(/10 entries/)).toBeTruthy();
  });

  it("renders the action type filter dropdown", () => {
    render(<AuditTrailWidget />, { wrapper });
    expect(screen.getByLabelText("Filter by action type")).toBeTruthy();
  });

  it("renders the CSV export button", () => {
    render(<AuditTrailWidget />, { wrapper });
    expect(screen.getByLabelText("Export audit log to CSV")).toBeTruthy();
  });

  it("renders date filter input", () => {
    render(<AuditTrailWidget />, { wrapper });
    expect(screen.getByLabelText("Filter from date")).toBeTruthy();
  });
});

describe("AuditTrailWidget (connected)", () => {
  it("never renders the Sample data affordance when connected", async () => {
    mockConnected.mockReturnValue(true);
    mockActivityLog.mockResolvedValue({ entries: [], total: 0 });
    render(<AuditTrailWidget />, { wrapper });
    await screen.findByText("No audit entries available.");
    expect(screen.queryByText("Sample data")).toBeNull();
  });

  it("renders the honest empty state — not sample rows — on an empty live response", async () => {
    mockConnected.mockReturnValue(true);
    mockActivityLog.mockResolvedValue({ entries: [], total: 0 });
    render(<AuditTrailWidget />, { wrapper });

    // Honest empty state is shown...
    expect(await screen.findByText("No audit entries available.")).toBeTruthy();
    // ...and NOT a single fabricated SAMPLE row.
    expect(screen.queryByText(/BUY NIFTY 22500 CE/)).toBeNull();
    expect(screen.getByText(/0 entries/)).toBeTruthy();
  });

  it("renders live audit rows, not sample rows, when the live response has data", async () => {
    mockConnected.mockReturnValue(true);
    mockActivityLog.mockResolvedValue({
      entries: [
        {
          id: 501,
          timestamp: new Date().toISOString(),
          action: "order_placed",
          user: "live-trader",
          details: "BUY TATAMOTORS 1 lot @ MKT",
          ip: "203.0.113.7",
        },
      ],
      total: 1,
    });
    render(<AuditTrailWidget />, { wrapper });

    // Live row renders.
    expect(await screen.findByText(/BUY TATAMOTORS/)).toBeTruthy();
    // A sample-only row must never appear for a connected user.
    expect(screen.queryByText(/BUY NIFTY 22500 CE/)).toBeNull();
    // No Sample data affordance in connected mode.
    expect(screen.queryByText("Sample data")).toBeNull();
  });
});
