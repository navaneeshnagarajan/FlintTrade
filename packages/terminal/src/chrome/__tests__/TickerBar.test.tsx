/**
 * TickerBar.test.tsx
 *
 * Tests for the TickerBar chrome component — renders live index prices
 * from Jotai indicesSummaryAtom.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";
import { MemoryRouter } from "react-router-dom";
import { Provider as JotaiProvider } from "jotai";
import { createStore } from "jotai";
import type { WsTick } from "@/types/api";

// Mock the indicesSummaryAtom via the marketAtoms module
const mockIndicesData: { name: string; data: WsTick | null }[] = [];

vi.mock("@/atoms/marketAtoms", () => {
  const { atom } = require("jotai");
  return {
    indicesSummaryAtom: atom(() => mockIndicesData),
  };
});

// Mock GlossaryTooltip to simplify rendering
vi.mock("@/components/ui/GlossaryTooltip", () => ({
  GlossaryTooltip: ({ children }: { children: React.ReactNode }) => <span>{children}</span>,
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
  });

  it("renders without crashing", () => {
    setIndices([]);
    const { container } = renderTickerBar();
    expect(container).toBeTruthy();
  });

  it("shows 'Connect OpenAlgo' prompt when no live data", () => {
    setIndices([
      { name: "NIFTY 50", data: null },
      { name: "SENSEX", data: null },
    ]);
    renderTickerBar();

    expect(screen.getByText(/connect openalgo for live prices/i)).toBeInTheDocument();
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

    expect(screen.queryByText(/connect openalgo for live prices/i)).not.toBeInTheDocument();
  });
});
