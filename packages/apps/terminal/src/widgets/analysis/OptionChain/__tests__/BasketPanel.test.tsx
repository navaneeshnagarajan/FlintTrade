import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import BasketPanel from "../BasketPanel";
import type { BasketItem } from "../types";

describe("BasketPanel", () => {
  it("dispatches every leg with its captured contract identity", () => {
    const onOrder = vi.fn();
    const basket = [{
      symbol: "BANKNIFTY",
      exchange: "NFO",
      expiry: "2026-08-06",
      strike: 55_000,
      optionType: "CE" as const,
      ltp: 125,
    }] satisfies BasketItem[];

    render(
      <BasketPanel
        basket={basket}
        onRemove={vi.fn()}
        onClear={vi.fn()}
        onOrder={onOrder}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Buy All" }));

    expect(onOrder).toHaveBeenCalledWith(expect.objectContaining({
      symbol: "BANKNIFTY",
      exchange: "NFO",
      expiry: "2026-08-06",
      strike: 55_000,
      optionType: "CE",
      action: "B",
    }));
  });
});
