import { StrictMode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import FundingRateWidget from "../FundingRateWidget";
import { EXAMPLE_FUNDING_RATES } from "../sampleData";
import { useModeStore } from "@/stores/modeStore";
import { brokerAccountKey, useBrokerStore } from "@/stores/brokerStore";
import type { BrokerAccount } from "@/types/broker";
import * as ftApi from "@/services/ftApi";

const fetchSpy = vi.fn();

function connectedAccount(broker: string): BrokerAccount {
  return {
    source: "native", broker, account_id: "example-account", label: "Native account",
    status: "connected", connected_at: null, error_message: null, is_primary: false,
  };
}

function rowSymbols(): string[] {
  const table = screen.getByRole("table", { name: "Example perpetual funding rates" });
  return within(table).getAllByRole("rowheader").map((cell) => cell.textContent ?? "");
}

beforeEach(() => {
  vi.stubGlobal("fetch", fetchSpy);
  fetchSpy.mockReset();
  useBrokerStore.setState({ accounts: [], activeAccountId: null });
  useModeStore.setState({ mode: "explore" });
});
afterEach(() => vi.unstubAllGlobals());

describe("FundingRateWidget Example-only contract", () => {
  it("labels every illustrative figure and uses no market transport", () => {
    render(<StrictMode><FundingRateWidget /></StrictMode>);
    expect(screen.getByRole("status", { name: "Illustrative funding rates; no market feed" })).toHaveTextContent("Example");
    expect(screen.getByText(/fixed illustrative rates per funding period/i)).toHaveTextContent("hypothetical $10,000");
    expect(rowSymbols()).toHaveLength(EXAMPLE_FUNDING_RATES.length);
    expect(fetchSpy).not.toHaveBeenCalled();
    expect(screen.queryByRole("button", { name: /refresh/i })).not.toBeInTheDocument();
    expect(screen.queryByText(/updated:|next funding|predicted|Delta Exchange/i)).not.toBeInTheDocument();
  });

  it.each(["practice", "live"] as const)("does not show Example figures in brokerless %s", (mode) => {
    useModeStore.setState({ mode });
    render(<FundingRateWidget />);
    expect(screen.getByRole("status")).toHaveTextContent("Funding rates are Example only");
    expect(screen.getByText(/no native funding-rate source is available/i)).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    expect(screen.queryByText("BTCUSD")).not.toBeInTheDocument();
    expect(fetchSpy).not.toHaveBeenCalled();
    expect(useModeStore.getState().mode).toBe(mode);
  });

  it.each(["dhan", "upstox", "kotakneo", "groww", "indmoney"])(
    "%s connectivity cannot admit funding figures in Live or Practice", (broker) => {
      const account = connectedAccount(broker);
      useBrokerStore.setState({ accounts: [account], activeAccountId: brokerAccountKey(account) });
      useModeStore.setState({ mode: "live" });
      render(<FundingRateWidget />);
      expect(screen.queryByRole("table")).not.toBeInTheDocument();
      act(() => useModeStore.getState().setMode("practice"));
      expect(screen.queryByRole("table")).not.toBeInTheDocument();
      expect(screen.getByRole("status")).toHaveTextContent("Example only");
      expect(fetchSpy).not.toHaveBeenCalled();
    },
  );

  it("clears the illustration immediately when the operator leaves Example", () => {
    render(<FundingRateWidget />);
    expect(screen.getByText("BTCUSD")).toBeInTheDocument();
    act(() => useModeStore.getState().setMode("practice"));
    expect(screen.queryByText("BTCUSD")).not.toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    act(() => useModeStore.getState().setMode("explore"));
    expect(screen.getByRole("status", { name: "Illustrative funding rates; no market feed" })).toBeInTheDocument();
    expect(screen.getByText("BTCUSD")).toBeInTheDocument();
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("orders by magnitude, then signed rate, then symbol without changing examples", () => {
    render(<FundingRateWidget />);
    expect(rowSymbols()).toEqual(["SOLUSD", "ETHUSD", "BTCUSD", "XRPUSD"]);
    const cycle = screen.getByRole("button", { name: "Cycle sort order" });
    fireEvent.click(cycle);
    expect(cycle).toHaveTextContent("Sort: Highest rate");
    expect(rowSymbols()).toEqual(["SOLUSD", "BTCUSD", "XRPUSD", "ETHUSD"]);
    fireEvent.click(cycle);
    expect(rowSymbols()).toEqual(["BTCUSD", "ETHUSD", "SOLUSD", "XRPUSD"]);
    fireEvent.click(cycle);
    expect(rowSymbols()).toEqual(["SOLUSD", "ETHUSD", "BTCUSD", "XRPUSD"]);
  });

  it("computes long payment direction from signed rate and a stated hypothetical notional", () => {
    render(<FundingRateWidget />);
    const btc = screen.getByRole("rowheader", { name: "BTCUSD" }).closest("tr")!;
    const eth = screen.getByRole("rowheader", { name: "ETHUSD" }).closest("tr")!;
    const sol = screen.getByRole("rowheader", { name: "SOLUSD" }).closest("tr")!;
    const xrp = screen.getByRole("rowheader", { name: "XRPUSD" }).closest("tr")!;
    expect(within(btc).getByText("+0.0100%")).toHaveClass("text-profit");
    expect(within(btc).getByText("Pays $1.00")).toBeInTheDocument();
    expect(within(eth).getByText("-0.0200%")).toHaveClass("text-loss");
    expect(within(eth).getByText("Receives $2.00")).toBeInTheDocument();
    expect(within(sol).getByText("Pays $3.00")).toBeInTheDocument();
    expect(within(xrp).getByText("No payment")).toBeInTheDocument();
    expect(screen.getByText("+0.0050%")).toBeInTheDocument();
  });

  it("renders separately named illustrative histories for all fixed examples", () => {
    render(<FundingRateWidget />);
    for (const entry of EXAMPLE_FUNDING_RATES) {
      expect(screen.getByLabelText(`${entry.symbol} illustrative funding history`)).toBeInTheDocument();
      expect(entry.history).toHaveLength(7);
      expect(entry.history.at(-1)).toBe(entry.rate);
      expect(entry.history.every(Number.isFinite)).toBe(true);
    }
  });

  it("exports no retired funding request client", () => {
    expect("getCryptoFundingRates" in ftApi).toBe(false);
  });
});
