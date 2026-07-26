/**
 * RotationTab.test — the RRG views carried over from SectorMap.
 *
 * Pins the view switcher, the portfolio view's empty state and symbol
 * persistence key, and the RRGCanvas provenance badge failing closed
 * (adapted from the retired SectorMap suite).
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactElement } from "react";
import "@testing-library/jest-dom";

vi.stubGlobal(
  "ResizeObserver",
  class {
    observe() {}
    unobserve() {}
    disconnect() {}
  },
);

const mockUseRRGData = vi.fn();
vi.mock("@/hooks/useRRGData", () => ({
  useRRGData: (...args: unknown[]) => mockUseRRGData(...args),
}));

import RotationTab from "../tabs/RotationTab";
import { RRGCanvas } from "../RRGCanvas";
import type { RRGResponse } from "@/services/ftApi";

function renderTab(ui: ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
}

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  // JSDOM has no Canvas 2D implementation; the draw loop bails on a null
  // context, so the surrounding markup is what these tests exercise.
  HTMLCanvasElement.prototype.getContext = vi.fn().mockReturnValue(null);
  mockUseRRGData.mockReturnValue({ data: null, isLoading: false, isError: false, refetch: vi.fn() });
});

describe("RotationTab", () => {
  it("renders the Sectors and Portfolio view switcher with Sectors selected", () => {
    renderTab(<RotationTab />);
    expect(screen.getByRole("tab", { name: "Sectors" }).getAttribute("aria-selected")).toBe("true");
    expect(screen.getByRole("tab", { name: "Portfolio" }).getAttribute("aria-selected")).toBe("false");
  });

  it("shows the empty view when no RRG data is available", () => {
    renderTab(<RotationTab />);
    expect(screen.getByText("No stock data available")).toBeInTheDocument();
  });

  it("renders the RRG canvas chrome when sector data arrives", () => {
    mockUseRRGData.mockReturnValue({
      data: {
        benchmark: "NIFTY 50",
        tail_length: 8,
        is_sample_data: false,
        sectors: [],
      } satisfies RRGResponse,
      isLoading: false,
      isError: false,
      refetch: vi.fn(),
    });
    renderTab(<RotationTab />);
    expect(screen.getByText(/benchmark: NIFTY 50/)).toBeInTheDocument();
  });

  it("opens the Portfolio view (deep-linkable) with its add-symbol empty state", () => {
    renderTab(<RotationTab initialView="portfolio" />);
    expect(screen.getByRole("tab", { name: "Portfolio" }).getAttribute("aria-selected")).toBe("true");
    expect(screen.getByText("Add symbols above to plot them on the RRG")).toBeInTheDocument();
    expect(screen.getByLabelText("Add symbol to portfolio RRG")).toBeInTheDocument();
  });

  it("switches to Portfolio on click", () => {
    renderTab(<RotationTab />);
    fireEvent.click(screen.getByRole("tab", { name: "Portfolio" }));
    expect(screen.getByText("Add symbols above to plot them on the RRG")).toBeInTheDocument();
  });

  it("keeps the SectorMap-era localStorage key so saved symbol lists survive the merge", () => {
    localStorage.setItem("flinttrade_portfolio_rrg_symbols", JSON.stringify(["RELIANCE"]));
    renderTab(<RotationTab initialView="portfolio" />);
    expect(screen.getByText("RELIANCE")).toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------
// RRGCanvas provenance — the sample indicator must fail closed, exactly as
// the portfolio view's badge already does.
// ---------------------------------------------------------------------------

describe("RRGCanvas provenance", () => {
  /** `is_sample_data` is a required field in the TS type but optional on the
   *  wire, so the absent case needs an assertion to be expressible. */
  function rrgResponse(provenance: { is_sample_data?: boolean }): RRGResponse {
    return {
      benchmark: "NIFTY 50",
      tail_length: 2,
      sectors: [
        {
          symbol: "NIFTYIT",
          name: "Nifty IT",
          current_quadrant: "leading",
          tail: [
            { date: "2026-07-17", rs_ratio: 100.4, rs_momentum: 100.2 },
            { date: "2026-07-18", rs_ratio: 100.9, rs_momentum: 100.6 },
          ],
        },
      ],
      ...provenance,
    } as RRGResponse;
  }

  it("badges the plot as sample when the response omits is_sample_data", () => {
    render(<RRGCanvas data={rrgResponse({})} tailLength={2} />);
    expect(screen.getByText("sample data")).toBeInTheDocument();
  });

  it("drops the badge only on an explicit is_sample_data: false", () => {
    render(<RRGCanvas data={rrgResponse({ is_sample_data: false })} tailLength={2} />);
    expect(screen.queryByText("sample data")).not.toBeInTheDocument();
  });

  it("badges the plot as sample on an explicit is_sample_data: true", () => {
    render(<RRGCanvas data={rrgResponse({ is_sample_data: true })} tailLength={2} />);
    expect(screen.getByText("sample data")).toBeInTheDocument();
  });
});
