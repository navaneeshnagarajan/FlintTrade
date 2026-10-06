/** Index-card observations must disclose Example provenance and missing prices. */

import { describe, it, expect, beforeAll, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";
import { createStore, Provider } from "jotai";
import { makeWidgetPanelProps } from "@/test-utils/widgetPanelProps";
import { tickAtomFamily } from "@/atoms/marketAtoms";
import { useModeStore } from "@/stores/modeStore";
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

const defaultProps = makeWidgetPanelProps();

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
    useModeStore.setState({ mode: "practice" });
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
    // Native cold-start has no observations.
    expect(screen.getAllByText("Awaiting price")).toHaveLength(5);
    expect(screen.getAllByLabelText(/awaiting native price/i)).toHaveLength(5);
    // No card renders a price or a sparkline that would imply one.
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
    // The header badge does not claim live data.
    expect(screen.getByRole("status")).toHaveTextContent("Awaiting quotes");
    expect(screen.queryByText("Live")).not.toBeInTheDocument();
  });

  it("renders a native quote with change, change% and sparkline once a price arrives", () => {
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
    // The badge describes native provenance only with a usable lead observation.
    expect(screen.getByRole("status")).toHaveTextContent("Native quotes");
    expect(screen.getByRole("status")).toHaveAccessibleName("Index cards show native broker quotes from REST polling");
    // The other four cards still say they are waiting — a partially-populated
    // strip never claims data it does not have.
    expect(screen.getAllByText("Awaiting price")).toHaveLength(4);
  });

  it("colours a falling index as a loss with a signed change", () => {
    seedTick("BSE_INDEX:SENSEX", { ltp: 72400, prevClose: 72800 });
    renderWidget();

    const change = screen.getByText("-400.00");
    expect(change).toBeInTheDocument();
    expect(change.parentElement).toHaveClass("text-loss");
  });

  it("keeps the badge awaiting when only a non-lead quote is available", () => {
    // Each card displays its own observation; the chip checks the lead index.
    seedTick("BSE_INDEX:SENSEX", { ltp: 72400, prevClose: 72800 });
    renderWidget();
    expect(screen.getByRole("status")).toHaveTextContent("Awaiting quotes");
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
    // A partial quote has no session reference; its change would be fabricated.
    seedTick("NSE_INDEX:NIFTY", { ltp: 22150.4 });
    renderWidget();
    expect(screen.getAllByText("Awaiting price")).toHaveLength(5);
    expect(screen.queryByText("22,150.4")).not.toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("Awaiting quotes");
  });

  it("labels simulated Example observations without claiming Live or WebSocket data", () => {
    useModeStore.setState({ mode: "explore" });
    seedTick("NSE_INDEX:NIFTY", { ltp: 22150.4, prevClose: 21965.15 });
    renderWidget();
    expect(screen.getByText("22,150.4")).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("Example");
    expect(screen.getByRole("status")).toHaveAccessibleName("Index cards show simulated Example prices");
    expect(screen.queryByText("Live")).not.toBeInTheDocument();
    expect(screen.queryByText("Native quotes")).not.toBeInTheDocument();
    expect(screen.getAllByLabelText(/awaiting example price/i)).toHaveLength(4);
  });

  it.each([Number.NaN, Number.POSITIVE_INFINITY, -1, 0])("rejects unusable lead price %s", (ltp) => {
    seedTick("NSE_INDEX:NIFTY", { ltp, prevClose: 21965.15 });
    renderWidget();
    expect(screen.getByRole("status")).toHaveTextContent("Awaiting quotes");
    expect(screen.getAllByText("Awaiting price")).toHaveLength(5);
  });
});
