/**
 * AuditTrailWidget.test.tsx
 *
 * Tests: render, table headers, sample data, filters, CSV export button.
 */

import { describe, it, expect, vi, beforeAll } from "vitest";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
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

import AuditTrailWidget from "../AuditTrailWidget";

function wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

describe("AuditTrailWidget", () => {
  it("renders the widget header", () => {
    render(<AuditTrailWidget />, { wrapper });
    expect(screen.getByText("Audit Trail")).toBeTruthy();
  });

  it("renders SEBI badge", () => {
    render(<AuditTrailWidget />, { wrapper });
    expect(screen.getByText("SEBI 5yr")).toBeTruthy();
  });

  it("renders table column headers", () => {
    render(<AuditTrailWidget />, { wrapper });
    expect(screen.getByText("Timestamp (IST)")).toBeTruthy();
    expect(screen.getByText("Action")).toBeTruthy();
    expect(screen.getByText("Details")).toBeTruthy();
    expect(screen.getByText("User")).toBeTruthy();
    expect(screen.getByText("IP")).toBeTruthy();
  });

  it("renders sample audit entries", () => {
    render(<AuditTrailWidget />, { wrapper });
    expect(screen.getByText(/BUY NIFTY 22500 CE/)).toBeTruthy();
  });

  it("shows entry count in filter bar", () => {
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
