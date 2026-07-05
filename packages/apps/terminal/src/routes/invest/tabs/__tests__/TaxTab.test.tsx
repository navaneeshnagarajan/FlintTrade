/**
 * TaxTab.test.tsx — Render tests for the Tax Report tab.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
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
  useTaxSummary: () => ({
    data: mockSummary,
    isLoading: false,
    isError: false,
  }),
  useTaxReport: () => ({
    data: mockReport,
    isLoading: false,
    isError: false,
  }),
}));

// ---------------------------------------------------------------------------
// Import after mocks
// ---------------------------------------------------------------------------

import { TaxTab } from "../TaxTab";

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
  });

  it("renders the Tax Report heading", () => {
    renderWithProviders();
    expect(screen.getByText("Tax Report")).toBeInTheDocument();
  });

  it("displays the FY selector", () => {
    renderWithProviders();
    expect(screen.getByText("FY 2025-26")).toBeInTheDocument();
  });

  it("displays trade count", () => {
    renderWithProviders();
    // Trade count appears in both header subtitle and hero card
    expect(screen.getAllByText(/50 trades/).length).toBeGreaterThanOrEqual(1);
  });

  it("shows the sample data banner when the tax API marks the payload as sample", () => {
    renderWithProviders();
    expect(screen.getByText(/showing sample data/i)).toBeInTheDocument();
  });

  it("shows audit status badge", () => {
    renderWithProviders();
    expect(screen.getByText("No Audit Required")).toBeInTheDocument();
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
