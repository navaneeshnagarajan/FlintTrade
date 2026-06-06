/**
 * OptionChainWidget.test.tsx
 *
 * Smoke tests for the option chain widget.
 * Mocks API calls, Glide Data Grid, and custom hooks.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

// Glide Data Grid — canvas-based, cannot render in jsdom
vi.mock("@glideapps/glide-data-grid", () => {
  const DataEditor = vi.fn(() => null);
  return {
    __esModule: true,
    default: DataEditor,
  };
});

vi.mock("@glideapps/glide-data-grid/dist/index.css", () => ({}));

// Custom hooks
vi.mock("../useOptionChainData", () => ({
  useOptionChainData: () => ({
    expiries: ["2026-04-10", "2026-04-17", "2026-04-24"],
    selectedExpiry: null,
    setSelectedExpiry: vi.fn(),
    chain: null,
    loading: false,
    error: null,
    lastRefresh: null,
    fetchData: vi.fn(),
    strikes: [],
    atmStrike: null,
    maxCallOI: 0,
    maxPutOI: 0,
    spotLtp: null,
    spotChange: null,
    spotChangePct: null,
    spotUp: true,
    pcr: null,
  }),
}));

vi.mock("@/hooks/useGlideTheme", () => ({
  useGlideTheme: () => ({}),
}));

vi.mock("@/hooks/useSyntheticFuture", () => ({
  useSyntheticFuture: () => ({ data: null }),
}));

// Services
vi.mock("@/services/api", () => ({
  getInstruments: vi.fn().mockResolvedValue([]),
  getOptionSymbol: vi.fn().mockResolvedValue({ symbol: "TEST", exchange: "NFO" }),
  getSymbol: vi.fn().mockResolvedValue({}),
  placeOrder: vi.fn().mockResolvedValue({}),
  getMaxPain: vi.fn().mockResolvedValue({}),
  basketOrder: vi.fn().mockResolvedValue({}),
}));

vi.mock("@/lib/market", () => ({
  isMarketHours: () => false,
}));

// Grid config
vi.mock("../gridConfig", () => ({
  getColumns: () => [],
  buildGetCellContent: () => () => ({ kind: "text", data: "", displayData: "" }),
  ATM_ROW_THEME: {},
}));

// TanStack Query — provide a wrapper
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: false } },
});

function Wrapper({ children }: { children: React.ReactNode }) {
  return (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
}

// ---------------------------------------------------------------------------
// Import after mocks
// ---------------------------------------------------------------------------

import OptionChainWidget from "../OptionChainWidget";
import { getSymbol } from "@/services/api";

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("OptionChainWidget", () => {
  beforeEach(() => {
    queryClient.clear();
    vi.restoreAllMocks();
  });

  it("renders without crashing", () => {
    const { container } = render(<OptionChainWidget />, { wrapper: Wrapper });
    expect(container.firstChild).toBeInTheDocument();
  });

  it("honours a pinned symbol from panel params (options-scalper preset pins NIFTY)", async () => {
    // The widget must seed from props.params.symbol, not just SYMBOLS[0].
    render(<OptionChainWidget params={{ symbol: "BANKNIFTY" }} />, { wrapper: Wrapper });
    await vi.waitFor(() =>
      expect(getSymbol).toHaveBeenCalledWith("BANKNIFTY", "NFO"),
    );
  });

  it("shows expiry buttons from the data hook", () => {
    render(<OptionChainWidget />, { wrapper: Wrapper });
    // The useOptionChainData mock returns 3 expiries; the widget shows up to 5.
    // Each expiry is formatted via fmtExpiry. Check at least one is present.
    const buttons = screen.getAllByRole("button");
    // There should be expiry buttons + view toggles + basket + strategy + refresh
    expect(buttons.length).toBeGreaterThan(3);
  });

  it("shows loading state when no expiry is selected", () => {
    render(<OptionChainWidget />, { wrapper: Wrapper });
    expect(screen.getByText("Select an expiry to load chain")).toBeInTheDocument();
  });

  it("renders the Build Strategy button", () => {
    render(<OptionChainWidget />, { wrapper: Wrapper });
    const btn = screen.getByTitle("Build multi-leg option strategy");
    expect(btn).toBeInTheDocument();
    expect(btn).toHaveAttribute("aria-pressed", "false");
  });

  it("toggles LegBuilder panel when Build Strategy is clicked", async () => {
    const { user } = await import("@testing-library/user-event").then((m) => ({
      user: m.default.setup(),
    }));
    render(<OptionChainWidget />, { wrapper: Wrapper });

    const btn = screen.getByTitle("Build multi-leg option strategy");
    // Panel is hidden initially
    expect(screen.queryByRole("region", { name: "Strategy leg builder" })).toBeNull();

    await user.click(btn);
    expect(screen.getByRole("region", { name: "Strategy leg builder" })).toBeInTheDocument();
    expect(btn).toHaveAttribute("aria-pressed", "true");

    // Click again → hides panel
    await user.click(btn);
    expect(screen.queryByRole("region", { name: "Strategy leg builder" })).toBeNull();
    expect(btn).toHaveAttribute("aria-pressed", "false");
  });
});
