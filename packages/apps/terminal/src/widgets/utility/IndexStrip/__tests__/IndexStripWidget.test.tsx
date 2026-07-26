/**
 * IndexStripWidget tests — the index cards extracted from the retired
 * Dashboard widget.
 *
 * Pins the data-honesty contract (the MarketSummary pattern): every level is
 * a live WebSocket tick from the Jotai atoms, a card with no tick says
 * "Awaiting tick" rather than inventing a number, and the header chip claims
 * "Live" only once the lead index has actually ticked. Explore mode gets the
 * same honest awaiting state — there are no demo prices to badge.
 */

import { describe, it, expect, beforeAll, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";
import { createStore, Provider } from "jotai";
import { makeDockviewPanelProps } from "@/test-utils/dockviewPanelProps";
import { tickAtomFamily } from "@/atoms/marketAtoms";
import IndexStripWidget from "../IndexStripWidget";

beforeAll(() => {
  global.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
});

/** Jotai store seeded per test so cards can be given a live tick. */
let store = createStore();

function seedTick(
  key: string,
  tick: { ltp: number; prevClose?: number; open?: number; high?: number; low?: number },
) {
  store.set(tickAtomFamily(key), tick as never);
}

const defaultProps = makeDockviewPanelProps();

function renderWidget() {
  return render(
    <Provider store={store}>
      <IndexStripWidget {...defaultProps} />
    </Provider>,
  );
}

describe("IndexStripWidget", () => {
  beforeEach(() => {
    store = createStore();
  });

  it("renders all five index cards from the retired Dashboard", () => {
    renderWidget();
    expect(screen.getByText("NIFTY 50")).toBeInTheDocument();
    expect(screen.getByText("BANK NIFTY")).toBeInTheDocument();
    expect(screen.getByText("SENSEX")).toBeInTheDocument();
    expect(screen.getByText("FIN NIFTY")).toBeInTheDocument();
    expect(screen.getByText("VIX")).toBeInTheDocument();
  });

  it("shows an honest awaiting state with no fabricated levels when no tick has arrived", () => {
    renderWidget();
    // Every card says so explicitly (the Explore / cold-start rendering).
    expect(screen.getAllByText("Awaiting tick")).toHaveLength(5);
    expect(screen.getAllByLabelText(/awaiting live price/i)).toHaveLength(5);
    // No card renders a price or a sparkline that would imply one.
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
    // The header badge does not claim live data.
    expect(screen.getByRole("status")).toHaveTextContent("Awaiting ticks");
    expect(screen.queryByText("Live")).not.toBeInTheDocument();
  });

  it("renders a live card with change, change% and sparkline once a tick arrives", () => {
    // 22150.4 against a 21965.15 previous close = +185.25 (+0.84%).
    seedTick("NSE_INDEX:NIFTY", {
      ltp: 22150.4,
      prevClose: 21965.15,
      open: 21990,
      high: 22180,
      low: 21950,
    });
    renderWidget();

    expect(screen.getByText("22,150.4")).toBeInTheDocument();
    expect(screen.getByText("+185.25")).toBeInTheDocument();
    expect(screen.getByText(/\+0\.84%/)).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "NIFTY 50 OHLC sparkline" })).toBeInTheDocument();
    // The badge flips to Live on evidence of the lead index tick.
    expect(screen.getByRole("status")).toHaveTextContent("Live");
    // The other four cards still say they are waiting — a partially-populated
    // strip never claims data it does not have.
    expect(screen.getAllByText("Awaiting tick")).toHaveLength(4);
  });

  it("colours a falling index as a loss with a signed change", () => {
    seedTick("BSE_INDEX:SENSEX", { ltp: 72400, prevClose: 72800 });
    renderWidget();

    const change = screen.getByText("-400.00");
    expect(change).toBeInTheDocument();
    expect(change.parentElement).toHaveClass("text-loss");
  });

  it("keeps the badge on Awaiting when only a non-lead index has ticked", () => {
    // The chip's evidence is the lead (NIFTY) tick, mirroring MarketSummary.
    seedTick("BSE_INDEX:SENSEX", { ltp: 72400, prevClose: 72800 });
    renderWidget();
    expect(screen.getByRole("status")).toHaveTextContent("Awaiting ticks");
  });

  it("flags a VIX level above 20 with the warning border", () => {
    seedTick("NSE_INDEX:INDIAVIX", { ltp: 23.5, prevClose: 19.8 });
    const { container } = renderWidget();
    expect(container.querySelector("[data-vix-warning]")).toBeInTheDocument();
  });

  it("does not flag a calm VIX", () => {
    seedTick("NSE_INDEX:INDIAVIX", { ltp: 12.4, prevClose: 12.9 });
    const { container } = renderWidget();
    expect(container.querySelector("[data-vix-warning]")).not.toBeInTheDocument();
  });

  it("treats a tick without a usable previous close as awaiting, not as a level", () => {
    // LTP-mode WebSocket sends no close; until usePrevClose merges prevClose
    // in, a change% would be fabricated — so the card must keep waiting.
    seedTick("NSE_INDEX:NIFTY", { ltp: 22150.4 });
    renderWidget();
    expect(screen.getAllByText("Awaiting tick")).toHaveLength(5);
    expect(screen.queryByText("22,150.4")).not.toBeInTheDocument();
  });
});
