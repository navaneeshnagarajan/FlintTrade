/**
 * TickerBar.test.tsx
 *
 * Tests for the TickerBar chrome component — renders live index prices
 * from Jotai indicesSummaryAtom. Includes coverage for MCX commodity
 * instruments (GOLD, SILVER, CRUDEOIL, NATGAS) which have extended hours.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";
import { MemoryRouter } from "react-router";
import { Provider as JotaiProvider } from "jotai";
import { createStore } from "jotai";
import type { WsTick } from "@/types/api";

// Mock the indicesSummaryAtom via the marketAtoms module
const mockIndicesData: { name: string; data: WsTick | null }[] = [];

vi.mock("@/atoms/marketAtoms", async (importOriginal) => {
  const { atom } = require("jotai");
  return {
    ...(await importOriginal<typeof import("@/atoms/marketAtoms")>()),
    indicesSummaryAtom: atom(() => mockIndicesData),
  };
});

// Mock GlossaryTooltip to simplify rendering
vi.mock("@/components/ui/GlossaryTooltip", () => ({
  GlossaryTooltip: ({ children }: { children: React.ReactNode }) => <span>{children}</span>,
}));

// isMarketHours mock — controlled per test
const mockIsMarketHours = vi.fn().mockReturnValue(false);
vi.mock("@/lib/market", () => ({
  isMarketHours: (...args: unknown[]) => mockIsMarketHours(...args),
}));

import TickerBar from "../TickerBar";

function renderTickerBar() {
  const store = createStore();
  return render(
    <JotaiProvider store={store}>
      <MemoryRouter>
        <TickerBar />
      </MemoryRouter>
    </JotaiProvider>,
  );
}

function setIndices(indices: { name: string; data: WsTick | null }[]) {
  mockIndicesData.length = 0;
  mockIndicesData.push(...indices);
}

describe("TickerBar", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    mockIndicesData.length = 0;
    mockIsMarketHours.mockReturnValue(false);
  });

  it("renders without crashing", () => {
    setIndices([]);
    const { container } = renderTickerBar();
    expect(container).toBeTruthy();
  });

  it("shows broker connect prompt when no live data", () => {
    setIndices([
      { name: "NIFTY 50", data: null },
      { name: "SENSEX", data: null },
    ]);
    renderTickerBar();

    expect(screen.getByText(/connect broker for live prices/i)).toBeInTheDocument();
  });

  it("shows index names when data is present", () => {
    setIndices([
      { name: "NIFTY 50", data: { ltp: 23500.50, prevClose: 23400 } as WsTick },
      { name: "SENSEX", data: { ltp: 77200.00, prevClose: 77000 } as WsTick },
    ]);
    renderTickerBar();

    expect(screen.getByText("NIFTY 50")).toBeInTheDocument();
    expect(screen.getByText("SENSEX")).toBeInTheDocument();
  });

  it("displays LTP values for indices with data", () => {
    setIndices([
      { name: "NIFTY 50", data: { ltp: 23500.50, prevClose: 23400 } as WsTick },
    ]);
    renderTickerBar();

    // LTP formatted as en-IN with 2 decimal places
    expect(screen.getByText("23,500.50")).toBeInTheDocument();
  });

  it("has the market indices region landmark", () => {
    setIndices([]);
    renderTickerBar();

    expect(screen.getByRole("region", { name: "Market indices" })).toBeInTheDocument();
  });

  it("does not show connect prompt when live data exists", () => {
    setIndices([
      { name: "NIFTY 50", data: { ltp: 23500.50 } as WsTick },
    ]);
    renderTickerBar();

    expect(screen.queryByText(/connect broker for live prices/i)).not.toBeInTheDocument();
  });

  // ---------------------------------------------------------------------------
  // MCX instruments
  // ---------------------------------------------------------------------------

  describe("MCX commodities", () => {
    it("renders MCX section separator when MCX instruments are present", () => {
      setIndices([
        { name: "NIFTY 50",  data: null },
        { name: "GOLD",      data: null },
        { name: "SILVER",    data: null },
        { name: "CRUDEOIL",  data: null },
        { name: "NATGAS",    data: null },
      ]);
      renderTickerBar();

      // The MCX label badge should be present
      expect(screen.getByLabelText(/MCX (open|closed)/i)).toBeInTheDocument();
    });

    it("does not render MCX separator when no MCX instruments are in the atom", () => {
      setIndices([
        { name: "NIFTY 50", data: null },
        { name: "SENSEX",   data: null },
      ]);
      renderTickerBar();

      expect(screen.queryByLabelText(/MCX (open|closed)/i)).not.toBeInTheDocument();
    });

    it("renders MCX commodity chip names", () => {
      setIndices([
        { name: "GOLD",     data: { ltp: 72500.00 } as WsTick },
        { name: "SILVER",   data: { ltp: 89500.00 } as WsTick },
        { name: "CRUDEOIL", data: { ltp: 6800.00  } as WsTick },
        { name: "NATGAS",   data: { ltp: 230.00   } as WsTick },
      ]);
      renderTickerBar();

      expect(screen.getByText("GOLD")).toBeInTheDocument();
      expect(screen.getByText("SILVER")).toBeInTheDocument();
      expect(screen.getByText("CRUDEOIL")).toBeInTheDocument();
      expect(screen.getByText("NATGAS")).toBeInTheDocument();
    });

    it("shows MCX badge as 'MCX open' when MCX session is active", () => {
      mockIsMarketHours.mockImplementation((exchange?: string) => exchange === "MCX");

      setIndices([
        { name: "GOLD", data: { ltp: 72500.00 } as WsTick },
      ]);
      renderTickerBar();

      const badge = screen.getByLabelText("MCX open");
      expect(badge).toBeInTheDocument();
      expect(badge).toHaveAttribute("title", "MCX session is open (09:00–23:30 IST)");
    });

    it("shows MCX badge as 'MCX closed' when MCX session is inactive", () => {
      mockIsMarketHours.mockReturnValue(false);

      setIndices([
        { name: "GOLD", data: null },
      ]);
      renderTickerBar();

      const badge = screen.getByLabelText("MCX closed");
      expect(badge).toBeInTheDocument();
      expect(badge).toHaveAttribute("title", "MCX session is closed");
    });

    it("MCX instruments display LTP values correctly", () => {
      setIndices([
        { name: "GOLD", data: { ltp: 72500.00, prevClose: 72000 } as WsTick },
      ]);
      renderTickerBar();

      expect(screen.getByText("72,500.00")).toBeInTheDocument();
    });

    it("MCX instruments are visible even when NSE is closed", () => {
      // NSE closed, MCX open — MCX instruments still render
      mockIsMarketHours.mockImplementation((exchange?: string) => exchange === "MCX");

      setIndices([
        { name: "NIFTY 50", data: null },
        { name: "GOLD",     data: { ltp: 72500.00 } as WsTick },
      ]);
      renderTickerBar();

      expect(screen.getByText("GOLD")).toBeInTheDocument();
      expect(screen.getByText("72,500.00")).toBeInTheDocument();
    });

    it("MCX section has accessible label", () => {
      setIndices([
        { name: "GOLD", data: null },
      ]);
      renderTickerBar();

      expect(
        screen.getByLabelText("MCX commodities section"),
      ).toBeInTheDocument();
    });
  });
});
