import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { SymbolRow } from "../SymbolRow";
import type { WatchlistItem } from "../types";

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
