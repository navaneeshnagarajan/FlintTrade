import { describe, it, expect, vi } from "vitest";
import { act, render, screen, fireEvent } from "@testing-library/react";
import { createStore, Provider } from "jotai";
import { tickAtomFamily } from "@/atoms/marketAtoms";
import { SymbolRow } from "../SymbolRow";
import type { WatchlistItem } from "../types";
import { brokerAccountKey, useBrokerStore } from "@/stores/brokerStore";
import { useModeStore } from "@/stores/modeStore";
import type { BrokerAccount } from "@/types/broker";

const ITEM: WatchlistItem = { symbol: "RELIANCE", exchange: "NSE" };

function renderRow(overrides: Partial<React.ComponentProps<typeof SymbolRow>> = {}) {
  return render(
    <SymbolRow
      item={ITEM}
      quote={{ ltp: 2850, prev_close: 2840 }}
      sparkPrices={[]}
      visibleColumns={["symbol", "price"]}
      formula="rangePct"
      onSelect={vi.fn()}
      onRemove={vi.fn()}
      {...overrides}
    />,
  );
}

describe("SymbolRow quick trade (W2)", () => {
  it("renders Buy/Sell buttons when onQuickTrade is provided", () => {
    renderRow({ onQuickTrade: vi.fn() });
    expect(screen.getByLabelText("Buy RELIANCE")).toBeInTheDocument();
    expect(screen.getByLabelText("Sell RELIANCE")).toBeInTheDocument();
  });

  it("does not render Buy/Sell buttons without onQuickTrade", () => {
    renderRow();
    expect(screen.queryByLabelText("Buy RELIANCE")).not.toBeInTheDocument();
  });

  it("calls onQuickTrade with the correct side and stops row selection", () => {
    const onQuickTrade = vi.fn();
    const onSelect = vi.fn();
    renderRow({ onQuickTrade, onSelect });

    fireEvent.click(screen.getByLabelText("Buy RELIANCE"));
    expect(onQuickTrade).toHaveBeenCalledWith(ITEM, "BUY");

    fireEvent.click(screen.getByLabelText("Sell RELIANCE"));
    expect(onQuickTrade).toHaveBeenCalledWith(ITEM, "SELL");

    // The row's onSelect must not fire from a quick-trade click.
    expect(onSelect).not.toHaveBeenCalled();
  });
});

describe("SymbolRow LTP / % change columns (FT-TRADE-008)", () => {
  it("paints LTP and % change from the ticker tick atom when REST has no quote", () => {
    const store = createStore();
    store.set(tickAtomFamily("NSE:RELIANCE"), {
      symbol: "RELIANCE",
      exchange: "NSE",
      ltp: 2850,
      prevClose: 2840,
    });

    render(
      <Provider store={store}>
        <SymbolRow
          item={ITEM}
          quote={null}
          sparkPrices={[]}
          visibleColumns={["symbol", "price", "changePct"]}
          formula="rangePct"
          onSelect={vi.fn()}
          onRemove={vi.fn()}
        />
      </Provider>,
    );

    expect(screen.getByLabelText("RELIANCE LTP")).toHaveTextContent("2,850.00");
    expect(screen.getByLabelText("RELIANCE % change")).toHaveTextContent("+0.35%");
  });

  it("shows an honest em dash when the column is checked but no quote has arrived", () => {
    renderRow({
      quote: null,
      visibleColumns: ["symbol", "price", "changePct"],
    });

    expect(screen.getByLabelText("RELIANCE LTP")).toHaveTextContent("—");
    expect(screen.getByLabelText("RELIANCE % change")).toHaveTextContent("—");
  });

  it("hides LTP and % change when those columns are unchecked", () => {
    renderRow({ visibleColumns: ["symbol"] });

    expect(screen.queryByLabelText("RELIANCE LTP")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("RELIANCE % change")).not.toBeInTheDocument();
  });

  it("shows a brief loading ellipsis before the honest empty", () => {
    renderRow({
      quote: null,
      isLoading: true,
      visibleColumns: ["symbol", "price", "changePct"],
    });

    expect(screen.getByLabelText("RELIANCE LTP")).toHaveTextContent("…");
    expect(screen.getByLabelText("RELIANCE % change")).toHaveTextContent("…");
  });
});


describe("SymbolRow tick authority", () => {
  function nativeAccount(id: string): BrokerAccount {
    return { source: "native", broker: "dhan", account_id: id, label: id,
      status: "connected", connected_at: null, error_message: null, is_primary: false };
  }
  const a = nativeAccount("A");
  const b = nativeAccount("B");
  const tickA = { symbol: "RELIANCE", exchange: "NSE", ltp: 2850, prevClose: 2840 };

  function mountAccountARow() {
    useModeStore.setState({ mode: "live" });
    useBrokerStore.setState({ accounts: [a, b], activeAccountId: brokerAccountKey(a) });
    const store = createStore();
    store.set(tickAtomFamily("NSE:RELIANCE"), tickA);
    const view = render(<Provider store={store}><SymbolRow item={ITEM} quote={null} sparkPrices={[]}
      visibleColumns={["symbol", "price", "changePct"]} formula="rangePct" onSelect={vi.fn()} onRemove={vi.fn()} /></Provider>);
    expect(screen.getByLabelText("RELIANCE LTP")).toHaveTextContent("2,850.00");
    return { store, view };
  }

  it("hides cached A ticker prices immediately under B and admits only B observations", () => {
    const { store } = mountAccountARow();
    act(() => useBrokerStore.getState().setActiveAccount(brokerAccountKey(b)));
    expect(screen.getByLabelText("RELIANCE LTP")).toHaveTextContent("—");
    expect(screen.getByLabelText("RELIANCE % change")).toHaveTextContent("—");
    act(() => store.set(tickAtomFamily("NSE:RELIANCE"), { ...tickA, ltp: 4000, prevClose: 3900 }));
    expect(screen.getByLabelText("RELIANCE LTP")).toHaveTextContent("4,000.00");
    act(() => useBrokerStore.getState().setActiveAccount(brokerAccountKey(a)));
    expect(screen.getByLabelText("RELIANCE LTP")).toHaveTextContent("—");
  });

  it.each(["practice", "explore"] as const)("clears cached native ticker observations before the first %s row render", (mode) => {
    mountAccountARow();
    act(() => useModeStore.getState().setMode(mode));
    expect(screen.getByLabelText("RELIANCE LTP")).toHaveTextContent("—");
    expect(screen.getByLabelText("RELIANCE % change")).toHaveTextContent("—");
  });
});
