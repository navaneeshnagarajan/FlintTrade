import { render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";
import { describe, expect, it } from "vitest";
import { Provider, createStore } from "jotai";

import { MiniChartCard } from "../MiniChartCard";
import { niftyAtom } from "@/atoms/marketAtoms";

describe("MiniChartCard", () => {
  it("renders the NIFTY illustrative sparkline through the shared Flint primitive", () => {
    render(<MiniChartCard />);

    const sparkline = screen.getByRole("img", { name: /NIFTY 50 1D illustrative sparkline/i });
    expect(sparkline).toHaveAttribute("viewBox", "0 0 160 42");
    expect(sparkline.querySelector("polyline")).not.toBeInTheDocument();
    expect(sparkline.querySelectorAll("path").length).toBeGreaterThan(0);
  });

  it("badges the sparkline as Demo (it is illustrative shape, not live data)", () => {
    render(<MiniChartCard />);
    expect(screen.getByTestId("mini-chart-demo-badge")).toHaveTextContent(/demo/i);
  });

  it("shows a dash, never a fabricated price, when there is no live NIFTY tick", () => {
    render(<MiniChartCard />);
    // House rule: no unguarded placeholder price on a live surface. The old card
    // hardcoded "22,400" — the headline must now be a dash without real data.
    expect(screen.getByTestId("mini-chart-ltp")).toHaveTextContent("—");
    expect(screen.queryByText(/22,400/)).not.toBeInTheDocument();
  });

  it("reflects the live NIFTY atom when a tick is present", () => {
    const store = createStore();
    store.set(niftyAtom, {
      symbol: "NIFTY",
      exchange: "NSE_INDEX",
      ltp: 22510.5,
      change: 110,
      pct: 0.49,
    });

    render(
      <Provider store={store}>
        <MiniChartCard />
      </Provider>,
    );

    expect(screen.getByTestId("mini-chart-ltp")).toHaveTextContent("22,510.5");
    expect(screen.getByText(/\+110 \(\+0\.49%\)/)).toBeInTheDocument();
  });
});
