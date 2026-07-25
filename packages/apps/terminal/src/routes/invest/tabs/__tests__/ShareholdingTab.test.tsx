/**
 * ShareholdingTab.test.tsx — render tests for the shareholding tab.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import "@testing-library/jest-dom";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

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
          dark: { colors: { card: "#16161f", border: "#2a2a3a", cardHover: "#1e1e2e" }, glass: { blur: 12, minOpacity: 0.8 } },
          light: { colors: { card: "#ffffff", border: "#e5e7eb", cardHover: "#f9fafb" }, glass: { blur: 12, minOpacity: 0.8 } },
        }),
        getResolvedMode: () => "dark",
      }),
    { getState: () => ({ glass: { enabled: false } }) },
  ),
}));

vi.mock("@/lib/cinematicThemes", () => ({
  getResolvedVariant: () => ({
    colors: { card: "#16161f", border: "#2a2a3a", cardHover: "#1e1e2e" },
    glass: { blur: 12, minOpacity: 0.8 },
  }),
}));

vi.mock("@/components/ui/DemoBanner", () => ({
  DemoBanner: () => <div data-testid="demo-banner">Demo mode</div>,
}));

// TanStack Query — disabled (no symbol yet) → data=undefined, isLoading=false
vi.mock("@tanstack/react-query", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@tanstack/react-query")>();
  return {
    ...actual,
    useQuery: vi.fn(() => ({
      data: undefined,
      isLoading: false,
      isError: false,
      refetch: vi.fn(),
    })),
  };
});

// ---------------------------------------------------------------------------
// Import after mocks
// ---------------------------------------------------------------------------

import { ShareholdingTab } from "../ShareholdingTab";
import { useQuery } from "@tanstack/react-query";

const mockUseQuery = useQuery as unknown as ReturnType<typeof vi.fn>;

const NO_DATA = { data: undefined, isLoading: false, isError: false, refetch: vi.fn() };

/** A complete server payload minus its provenance flag. */
const LIVE_PAYLOAD = {
  shareholding: {
    symbol: "TCS",
    as_of_quarter: "Jun 2025",
    promoter_pct: 71.77,
    fii_pct: 12.40,
    dii_pct: 10.80,
    public_pct: 5.03,
    government_pct: 0.00,
    promoter_history: [{ quarter: "Jun 2025", percentage: 71.77 }],
    fii_history: [{ quarter: "Jun 2025", percentage: 12.40 }],
    dii_history: [{ quarter: "Jun 2025", percentage: 10.80 }],
    public_history: [{ quarter: "Jun 2025", percentage: 5.03 }],
  },
  financials: {
    symbol: "TCS",
    revenue: 240893,
    net_profit: 48797,
    operating_cash_flow: 44338,
    debt_to_equity: 0.09,
    roe: 51.2,
    roce: 64.3,
    pe_ratio: 27.1,
    market_cap: 1265000,
    book_value: 260,
    annual_history: [
      { year: "Mar 2025", revenue: 240893, net_profit: 48797, operating_cash_flow: 44338 },
    ],
  },
  announcements: [],
};

/** The tab only leaves its "no symbol yet" demo state once a symbol is fetched. */
function fetchSymbol(symbol = "TCS") {
  fireEvent.change(screen.getByRole("textbox", { name: /enter nse\/bse symbol/i }), {
    target: { value: symbol },
  });
  fireEvent.click(screen.getByRole("button", { name: /fetch/i }));
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("ShareholdingTab", () => {
  beforeEach(() => {
    mockUseQuery.mockReturnValue(NO_DATA);
  });

  it("keeps the demo banner when the response omits is_sample_data", () => {
    // Provenance fails closed — an absent flag is sample, never live.
    mockUseQuery.mockReturnValue({ ...NO_DATA, data: LIVE_PAYLOAD });
    render(<ShareholdingTab />);
    fetchSymbol();
    expect(screen.getByTestId("demo-banner")).toBeInTheDocument();
  });

  it("drops the demo banner only on an explicit is_sample_data: false", () => {
    mockUseQuery.mockReturnValue({ ...NO_DATA, data: { ...LIVE_PAYLOAD, is_sample_data: false } });
    render(<ShareholdingTab />);
    fetchSymbol();
    expect(screen.queryByTestId("demo-banner")).not.toBeInTheDocument();
  });

  it("treats an absent response as demo once a symbol has been fetched", () => {
    // The tab renders DEMO_RESPONSE in this state, so it must say so.
    render(<ShareholdingTab />);
    fetchSymbol();
    expect(screen.getByTestId("demo-banner")).toBeInTheDocument();
  });

  it("renders the section heading", () => {
    render(<ShareholdingTab />);
    expect(screen.getByText("Shareholding Pattern")).toBeInTheDocument();
  });

  it("renders the symbol search input", () => {
    render(<ShareholdingTab />);
    expect(
      screen.getByRole("textbox", { name: /enter nse\/bse symbol/i }),
    ).toBeInTheDocument();
  });

  it("renders the Fetch button", () => {
    render(<ShareholdingTab />);
    expect(screen.getByRole("button", { name: /fetch/i })).toBeInTheDocument();
  });

  it("shows demo banner when showing sample data", () => {
    render(<ShareholdingTab />);
    expect(screen.getByTestId("demo-banner")).toBeInTheDocument();
  });

  it("shows demo symbol RELIANCE in the default state", () => {
    render(<ShareholdingTab />);
    expect(screen.getByText("RELIANCE")).toBeInTheDocument();
  });

  it("renders financial highlights section", () => {
    render(<ShareholdingTab />);
    expect(screen.getByText("Financial Highlights")).toBeInTheDocument();
    expect(screen.getByText("Revenue (Cr)")).toBeInTheDocument();
    expect(screen.getByText("Net Profit (Cr)")).toBeInTheDocument();
    expect(screen.getByText("ROE")).toBeInTheDocument();
    expect(screen.getByText("ROCE")).toBeInTheDocument();
    expect(screen.getByText("D/E Ratio")).toBeInTheDocument();
    expect(screen.getByText("P/E Ratio")).toBeInTheDocument();
  });

  it("renders corporate announcements section", () => {
    render(<ShareholdingTab />);
    expect(screen.getByText("Corporate Announcements")).toBeInTheDocument();
    // The demo has 3 announcements
    expect(screen.getByRole("list", { name: /corporate announcements/i })).toBeInTheDocument();
  });

  it("renders quarterly trend section with stacked bar", () => {
    render(<ShareholdingTab />);
    expect(screen.getByText("Quarterly Trend")).toBeInTheDocument();
    expect(screen.getByRole("img", { name: /shareholding trend/i })).toHaveAttribute(
      "data-flint-chart",
      "stacked-bar",
    );
    // Promoter label in legend
    expect(screen.getByText("Promoter")).toBeInTheDocument();
    expect(screen.getByText("FII")).toBeInTheDocument();
    expect(screen.getByText("DII")).toBeInTheDocument();
  });
});
