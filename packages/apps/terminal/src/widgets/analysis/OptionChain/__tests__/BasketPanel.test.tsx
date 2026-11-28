import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import BasketPanel from "../BasketPanel";
import type { BasketItem } from "../types";
import { tabTo } from "@/test-utils/tabTo";

const BASKET = [{
  symbol: "BANKNIFTY",
  exchange: "NFO",
  expiry: "2026-08-06",
  strike: 55_000,
  optionType: "CE" as const,
  ltp: 125,
}] satisfies BasketItem[];

function renderBasket(props: { locked?: boolean; statusUnknown?: boolean } = {}) {
  return render(
    <BasketPanel basket={BASKET} onRemove={vi.fn()} onClear={vi.fn()} onOrder={vi.fn()} {...props} />,
  );
}

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

  it.each([
    ["a lost submit", { locked: true, statusUnknown: true }, "Order status unknown. Check Orders before trying again."],
    ["a request in flight", { locked: true, statusUnknown: false }, "Order sent. Waiting for reply."],
  ])("explains Buy All and Sell All through a tooltip the keyboard reaches after %s", async (_label, props, reason) => {
    const user = userEvent.setup();
    renderBasket(props);

    for (const name of ["Buy All", "Sell All"]) {
      const button = screen.getByRole("button", { name });
      expect(button).toBeDisabled();
      await tabTo(user, button.parentElement as HTMLElement);
      expect(await screen.findByRole("tooltip")).toHaveTextContent(reason);
    }
  });

  it("adds no tab stop around Buy All and Sell All while they are enabled", async () => {
    const user = userEvent.setup();
    renderBasket();

    for (const name of ["Buy All", "Sell All"]) {
      const button = screen.getByRole("button", { name });
      expect(button.parentElement).not.toHaveAttribute("tabindex");
      await tabTo(user, button);
    }
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
  });
});
