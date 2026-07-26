/**
 * TaxTab.test.tsx — Render tests for the Tax Report tab.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

// Mock themeStore — GlassCard reads glass.enabled and activeThemeId
vi.mock("@/stores/themeStore", () => ({
  useThemeStore: Object.assign(
    (selector: (s: Record<string, unknown>) => unknown) =>
      selector({
        glass: { enabled: false, blur: 12, transparency: 20 },
        activeThemeId: "graphite",
        mode: "dark",
        customThemes: [],
        getActiveTheme: () => ({
          id: "graphite",
          name: "Graphite",
          dark: {
            colors: { card: "#16161f", border: "#2a2a3a", cardHover: "#1e1e2e" },
            glass: { blur: 12, minOpacity: 0.8 },
          },
          light: {
            colors: { card: "#ffffff", border: "#e5e7eb", cardHover: "#f9fafb" },
            glass: { blur: 12, minOpacity: 0.8 },
          },
        }),
        getResolvedMode: () => "dark",
      }),
    { getState: () => ({ glass: { enabled: false } }) },
  ),
}));

// Mock cinematicThemes
vi.mock("@/lib/cinematicThemes", () => ({
  getResolvedVariant: () => ({
    colors: { card: "#16161f", border: "#2a2a3a", cardHover: "#1e1e2e" },
    glass: { blur: 12, minOpacity: 0.8 },
  }),
}));

// Mock GlossaryTooltip — render children without tooltip wrapper
vi.mock("@/components/ui/GlossaryTooltip", () => ({
  GlossaryTooltip: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

// Mock the tax report hook
const { exportToCSVMock, useTaxSummaryMock, useTaxReportMock } = vi.hoisted(() => ({
  exportToCSVMock: vi.fn(),
  useTaxSummaryMock: vi.fn(),
  useTaxReportMock: vi.fn(),
}));

const mockSummary = {
  fy: "2025-26",
  equity_ltcg: 75000,
  equity_stcg: 12500,
  intraday_pnl: 3200,
  fno_pnl: 21500,
  commodity_pnl: -7500,
  stt_paid: 450.25,
  turnover: 185000,
  tax_liability_estimated: 12375,
  ltcg_exemption_used: 75000,
  needs_audit: false,
  audit_assessment: "incomplete",
  audit_assessment_reason: "Complete taxpayer-specific records are not available.",
  tax_estimate_methodology: "Indicative estimate from realised P&L using simplified assumptions.",
  stt_methodology: "STT is calculated using the rate effective on each transaction date.",
  stt_rate_provenance: "Finance (No. 2) Act, 2024 and Finance Act, 2026.",
  stt_rate_schedule: [],
  trade_count: 50,
  is_sample_data: true,
  data_source: "sample",
};

const mockReport = {
  summary: mockSummary,
  segments: {
    equity_ltcg: { trade_count: 5, pnl: 75000, trades: [] },
    equity_stcg: { trade_count: 5, pnl: 12500, trades: [] },
    equity_intraday: { trade_count: 12, pnl: 3200, trades: [] },
    futures: { trade_count: 8, pnl: 15000, trades: [] },
    options: { trade_count: 12, pnl: 6500, trades: [] },
    commodity: { trade_count: 8, pnl: -7500, trades: [] },
  },
};

vi.mock("@/hooks/useTaxReport", () => ({
  useTaxSummary: useTaxSummaryMock,
  useTaxReport: useTaxReportMock,
}));

vi.mock("@/lib/exportUtils", () => ({
  exportToCSV: exportToCSVMock,
  printCurrentView: vi.fn(),
}));

// ---------------------------------------------------------------------------
// Import after mocks
// ---------------------------------------------------------------------------

import { getFinancialYearOptions, TaxTab } from "../TaxTab";

// ---------------------------------------------------------------------------
// Helper
// ---------------------------------------------------------------------------

function renderWithProviders() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <TaxTab />
    </QueryClientProvider>,
  );
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("TaxTab", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useTaxSummaryMock.mockReturnValue({
      data: mockSummary,
      isLoading: false,
      isError: false,
    });
    useTaxReportMock.mockReturnValue({
      data: mockReport,
      isLoading: false,
      isError: false,
    });
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("renders the Tax Report heading", () => {
    renderWithProviders();
    expect(screen.getByText("Tax Report")).toBeInTheDocument();
  });

  it("derives current and previous Indian FY options from the current date", () => {
    expect(getFinancialYearOptions(new Date(2028, 1, 15))).toEqual([
      { value: "2027-28", label: "FY 2027-28" },
      { value: "2026-27", label: "FY 2026-27" },
    ]);
  });

  it("defaults requests to the dynamically derived current Indian FY", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date(2028, 6, 15));

    renderWithProviders();

    expect(useTaxSummaryMock).toHaveBeenCalledWith("2028-29");
    expect(useTaxReportMock).toHaveBeenCalledWith("2028-29");
    expect(screen.getByText("FY 2028-29")).toBeInTheDocument();
  });

  it("displays trade count", () => {
    renderWithProviders();
    // Trade count appears in both header subtitle and hero card
    expect(screen.getAllByText(/50 trades/).length).toBeGreaterThanOrEqual(1);
  });

  it("states that the built-in ledger is illustrative and live tax history is not wired", () => {
    renderWithProviders();
    expect(
      screen.getByText(/the built-in tax ledger is illustrative; live tax-history ingestion is not wired/i),
    ).toBeInTheDocument();
    expect(screen.queryByText(/connect a broker for live data/i)).not.toBeInTheDocument();
  });

  it("renders an incomplete audit assessment without a definitive clearance", () => {
    renderWithProviders();
    expect(screen.getAllByText("Audit assessment incomplete").length).toBeGreaterThanOrEqual(1);
    expect(screen.queryByText("No Audit Required")).not.toBeInTheDocument();
    expect(screen.queryByText("Below audit threshold")).not.toBeInTheDocument();
  });

  it("shows trade-date methodology and effective-date provenance", () => {
    renderWithProviders();

    expect(screen.getByText(/trade-date STT rates/i)).toBeInTheDocument();
    expect(screen.getByText(/Finance \(No\. 2\) Act, 2024 and Finance Act, 2026/i)).toBeInTheDocument();
    expect(screen.queryByText(/Budget 2024 rates/i)).not.toBeInTheDocument();
  });

  it("keeps the effective-dated STT schedule visible during local fallback", () => {
    useTaxSummaryMock.mockReturnValue({
      data: undefined,
      isLoading: false,
      isError: true,
    });
    useTaxReportMock.mockReturnValue({
      data: undefined,
      isLoading: false,
      isError: true,
    });

    renderWithProviders();

    expect(screen.getByText(/0\.0625%\/0\.0125% before 1 October 2024/i)).toBeInTheDocument();
    expect(screen.getByText(/0\.15%\/0\.05% from 1 April 2026/i)).toBeInTheDocument();
  });

  it("disables CSV export for sample tax data", () => {
    renderWithProviders();

    const exportButton = screen.getByRole("button", { name: /export csv/i });
    expect(exportButton).toBeDisabled();
    fireEvent.click(exportButton);
    expect(exportToCSVMock).not.toHaveBeenCalled();
  });

  it("treats a summary with no is_sample_data flag as demo", () => {
    // Provenance fails closed: an absent flag must not unlock the live-data
    // affordances (the illustrative banner stays, CSV export stays disabled).
    const { is_sample_data: _omitted, ...noProvenance } = mockSummary;
    useTaxSummaryMock.mockReturnValue({
      data: { ...noProvenance, data_source: "tax_history" },
      isLoading: false,
      isError: false,
    });

    renderWithProviders();

    expect(
      screen.getByText(/the built-in tax ledger is illustrative; live tax-history ingestion is not wired/i),
    ).toBeInTheDocument();
    const exportButton = screen.getByRole("button", { name: /export csv/i });
    expect(exportButton).toBeDisabled();
    fireEvent.click(exportButton);
    expect(exportToCSVMock).not.toHaveBeenCalled();
  });

  it("exports backend P&L and only the backend overall estimate and provenance", () => {
    useTaxSummaryMock.mockReturnValue({
      data: { ...mockSummary, is_sample_data: false, data_source: "tax_history" },
      isLoading: false,
      isError: false,
    });
    renderWithProviders();

    fireEvent.click(screen.getByRole("button", { name: /export csv/i }));

    expect(exportToCSVMock).toHaveBeenCalledOnce();
    const [rows, filename] = exportToCSVMock.mock.calls[0];
    expect(filename).toMatch(/^tax-summary-\d{4}-\d{2}$/);
    expect(rows.find((row: Record<string, unknown>) => row.Segment === "Commodity")).toEqual({
      Segment: "Commodity",
      "P&L": -7500,
    });
    expect(rows.filter((row: Record<string, unknown>) => "Estimated Tax" in row)).toEqual([
      {
        Segment: "Overall estimate",
        "P&L": 104700,
        "Estimated Tax": 12375,
        STT: 450.25,
        Methodology: mockSummary.tax_estimate_methodology,
        Provenance: mockSummary.stt_rate_provenance,
      },
    ]);
  });

  it("renders segment breakdown section", () => {
    renderWithProviders();
    expect(screen.getByText("Segment Breakdown")).toBeInTheDocument();
  });

  it("shows summary card labels", () => {
    renderWithProviders();
    // Labels appear in both summary cards and segment table, so use getAllByText
    expect(screen.getAllByText("Equity LTCG").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("Equity STCG").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("Intraday P&L")).toBeInTheDocument();
    expect(screen.getByText("F&O P&L")).toBeInTheDocument();
    expect(screen.getByText("Commodity P&L")).toBeInTheDocument();
    // STT appears in multiple places (card label + table)
    expect(screen.getAllByText(/STT/).length).toBeGreaterThanOrEqual(1);
  });

  it("displays turnover section", () => {
    renderWithProviders();
    expect(screen.getByText("Total Turnover")).toBeInTheDocument();
    expect(screen.getByText("Audit Threshold")).toBeInTheDocument();
    expect(screen.getByText("Audit Status")).toBeInTheDocument();
  });

  it("renders the disclaimer text", () => {
    renderWithProviders();
    expect(
      screen.getByText(/Tax calculations are estimates/),
    ).toBeInTheDocument();
  });
});
