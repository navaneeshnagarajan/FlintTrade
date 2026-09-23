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
const mockIndicesData: {
  name: string;
  data: WsTick | null;
  venue?: string;
  exchange?: string;
}[] = [];

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

import { useModeStore } from "@/stores/modeStore";
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

function setIndices(
  indices: { name: string; data: WsTick | null; venue?: string; exchange?: string }[],
) {
  mockIndicesData.length = 0;
  mockIndicesData.push(...indices);
}

describe("TickerBar", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    mockIndicesData.length = 0;
    mockIsMarketHours.mockReturnValue(false);
    useModeStore.setState({ mode: "explore" });
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

    expect(screen.getAllByText("NIFTY 50").length).toBeGreaterThan(0);
    expect(screen.getAllByText("SENSEX").length).toBeGreaterThan(0);
  });

  it("displays LTP values for indices with data", () => {
    setIndices([
      { name: "NIFTY 50", data: { ltp: 23500.50, prevClose: 23400 } as WsTick },
    ]);
    renderTickerBar();

    // LTP formatted as en-IN with 2 decimal places
    expect(screen.getAllByText("23,500.50").length).toBeGreaterThan(0);
  });

  it("shows a Sample feed-source chip in Explore (FT-CORE-002)", () => {
    setIndices([]);
    renderTickerBar();

    const chip = screen.getByTestId("feed-freshness-chip");
    expect(chip).toHaveTextContent("Sample");
    expect(chip).toHaveAttribute("data-state", "sample");
    expect(chip).not.toHaveTextContent("Live");
  });

  it("has the market indices region landmark", () => {
    setIndices([]);
    renderTickerBar();

    expect(screen.getByRole("region", { name: "Market indices" })).toBeInTheDocument();
    expect(screen.getByTestId("ticker-strip")).toBeInTheDocument();
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

      expect(screen.getAllByText("GOLD").length).toBeGreaterThan(0);
      expect(screen.getAllByText("SILVER").length).toBeGreaterThan(0);
      expect(screen.getAllByText("CRUDEOIL").length).toBeGreaterThan(0);
      expect(screen.getAllByText("NATGAS").length).toBeGreaterThan(0);
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

      expect(screen.getAllByText("72,500.00").length).toBeGreaterThan(0);
    });

    it("MCX instruments are visible even when NSE is closed", () => {
      // NSE closed, MCX open — MCX instruments still render
      mockIsMarketHours.mockImplementation((exchange?: string) => exchange === "MCX");

      setIndices([
        { name: "NIFTY 50", data: null },
        { name: "GOLD",     data: { ltp: 72500.00 } as WsTick },
      ]);
      renderTickerBar();

      expect(screen.getAllByText("GOLD").length).toBeGreaterThan(0);
      expect(screen.getAllByText("72,500.00").length).toBeGreaterThan(0);
    });

    it("groups the MCX badge with the venues that feed the tape", () => {
      setIndices([
        { name: "GOLD", data: null },
      ]);
      renderTickerBar();

      const badges = screen.getByLabelText("Venue badges");
      expect(badges).toHaveAttribute("data-venues", "MCX");
      expect(screen.getByLabelText("MCX closed")).toBeInTheDocument();
    });
  });

  describe("venue badges match the feeding tape", () => {
    const equityAndMcx = [
      { name: "NIFTY 50", data: null },
      { name: "SENSEX", data: null },
      { name: "BANK NIFTY", data: null },
      { name: "VIX", data: null },
      { name: "GOLD", data: null },
      { name: "SILVER", data: null },
      { name: "CRUDEOIL", data: null },
      { name: "NATGAS", data: null },
    ];

    it("shows NSE, BSE and MCX when equity indices scroll with MCX commodities", () => {
      setIndices(equityAndMcx);
      renderTickerBar();

      const badges = screen.getByTestId("ticker-venue-badges");
      expect(badges).toHaveAttribute("data-venues", "NSE,BSE,MCX");
      expect(screen.getByLabelText("NSE closed")).toBeInTheDocument();
      expect(screen.getByLabelText("BSE closed")).toBeInTheDocument();
      expect(screen.getByLabelText("MCX closed")).toBeInTheDocument();
      expect(screen.queryByText("Unavailable")).not.toBeInTheDocument();
      expect(screen.getAllByText("NIFTY 50").length).toBeGreaterThan(0);
      expect(screen.getAllByText("SENSEX").length).toBeGreaterThan(0);
      expect(screen.getAllByText("BANK NIFTY").length).toBeGreaterThan(0);
      expect(screen.getAllByText("VIX").length).toBeGreaterThan(0);
    });

    it("keeps each venue's session state when only MCX is open", () => {
      mockIsMarketHours.mockImplementation((exchange?: string) => exchange === "MCX");
      setIndices(equityAndMcx);
      renderTickerBar();

      expect(screen.getByLabelText("NSE closed")).toHaveAttribute(
        "title",
        "NSE session is closed",
      );
      expect(screen.getByLabelText("BSE closed")).toBeInTheDocument();
      expect(screen.getByLabelText("MCX open")).toHaveAttribute(
        "title",
        "MCX session is open (09:00–23:30 IST)",
      );
    });

    it("omits MCX when the tape is equity indices only", () => {
      setIndices([
        { name: "NIFTY 50", data: null },
        { name: "SENSEX", data: null },
        { name: "BANK NIFTY", data: null },
        { name: "VIX", data: null },
      ]);
      renderTickerBar();

      expect(screen.getByTestId("ticker-venue-badges")).toHaveAttribute(
        "data-venues",
        "NSE,BSE",
      );
      expect(screen.queryByLabelText(/MCX (open|closed)/i)).not.toBeInTheDocument();
    });

    it("adds NFO when an F&O symbol feeds the marquee", () => {
      setIndices([
        { name: "NIFTY 50", data: null },
        { name: "NIFTY 24500 CE", exchange: "NFO", data: null },
        { name: "GOLD", data: null },
      ]);
      renderTickerBar();

      expect(screen.getByTestId("ticker-venue-badges")).toHaveAttribute(
        "data-venues",
        "NSE,NFO,MCX",
      );
      expect(screen.getByLabelText("NFO closed")).toHaveAttribute(
        "title",
        "NFO session is closed",
      );
    });

    it("omits the badge strip when the marquee has no symbols", () => {
      setIndices([]);
      renderTickerBar();

      expect(screen.queryByTestId("ticker-venue-badges")).not.toBeInTheDocument();
      expect(screen.queryByText("Unavailable")).not.toBeInTheDocument();
    });

    it("shows Unavailable instead of a fake venue strip when symbols have no venue", () => {
      setIndices([{ name: "MYSTERY SCRIP", data: null }]);
      renderTickerBar();

      expect(screen.getByTestId("ticker-venue-badges")).toHaveAttribute(
        "data-venues",
        "unavailable",
      );
      expect(screen.getByLabelText("Venues unavailable")).toHaveTextContent("Unavailable");
      expect(screen.queryByLabelText(/NSE (open|closed)/i)).not.toBeInTheDocument();
      expect(screen.queryByLabelText(/BSE (open|closed)/i)).not.toBeInTheDocument();
      expect(screen.queryByLabelText(/MCX (open|closed)/i)).not.toBeInTheDocument();
    });
  });

  it("uses one scrolling marquee for the dedicated strip", () => {
    setIndices([
      { name: "NIFTY 50", data: { ltp: 23500.50, prevClose: 23400 } as WsTick },
    ]);
    renderTickerBar();

    expect(screen.getByTestId("ticker-strip")).toBeInTheDocument();
    const marquee = screen.getByTestId("ticker-marquee");
    expect(marquee).toHaveAttribute("data-motion", "marquee");
    expect(marquee.querySelector(".ticker-track")).not.toBeNull();
    expect(screen.queryByTestId("ticker-reduced-motion")).not.toBeInTheDocument();
    expect(screen.getAllByRole("region", { name: "Market indices" })).toHaveLength(1);
    expect(screen.queryByRole("region", { name: "Ticker prices" })).not.toBeInTheDocument();
  });

  it("freezes the marquee and labels reduced motion", () => {
    vi.spyOn(window, "matchMedia").mockImplementation((query: string) => ({
      matches: query.includes("prefers-reduced-motion"),
      media: query,
      onchange: null,
      addListener: () => {},
      removeListener: () => {},
      addEventListener: () => {},
      removeEventListener: () => {},
      dispatchEvent: () => false,
    }) as unknown as MediaQueryList);

    setIndices([
      { name: "NIFTY 50", data: { ltp: 23500.5, prevClose: 23400 } as WsTick },
      { name: "SENSEX", data: { ltp: 77200 } as WsTick },
    ]);
    renderTickerBar();

    const marquee = screen.getByTestId("ticker-marquee");
    expect(marquee).toHaveAttribute("data-motion", "reduced");
    expect(marquee.querySelector(".ticker-track")).toBeNull();
    expect(screen.getByTestId("ticker-reduced-motion")).toHaveTextContent("Reduced motion");
    expect(screen.getAllByText("NIFTY 50")).toHaveLength(1);
  });
});
