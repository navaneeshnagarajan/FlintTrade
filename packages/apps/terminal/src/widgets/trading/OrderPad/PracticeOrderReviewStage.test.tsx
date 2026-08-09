import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import "@testing-library/jest-dom";
import { PracticeOrderReviewStage } from "./PracticeOrderReviewStage";
import { createPracticeOrderReviewSnapshot } from "./practiceOrderReview";

const review = createPracticeOrderReviewSnapshot(
  {
    symbol: "RELIANCE",
    exchange: "NSE",
    action: "BUY",
    orderType: "LIMIT",
    product: "CNC",
    qty: 2,
    price: 1_250.5,
    trigPrice: undefined,
    discQty: undefined,
  },
  {
    symbol: "RELIANCE",
    exchange: "NSE",
    action: "BUY",
    orderType: "LIMIT",
    product: "CNC",
    quantity: 2,
    price: 1_250.5,
    triggerPrice: 0,
    strategy: "FlintOrderPad",
  },
);

describe("PracticeOrderReviewStage", () => {
  it("exposes a labelled modal dialog and supports keyboard-only confirmation", async () => {
    const user = userEvent.setup();
    const onConfirm = vi.fn();
    render(
      <PracticeOrderReviewStage
        review={review}
        confirming={false}
        onBack={vi.fn()}
        onConfirm={onConfirm}
      />,
    );

    const dialog = screen.getByRole("dialog", { name: "Review Practice order" });
    expect(dialog).toHaveAttribute("aria-modal", "true");
    expect(dialog).toHaveAccessibleDescription(/simulation only/i);

    const back = screen.getByRole("button", { name: "Back to edit" });
    const confirm = screen.getByRole("button", { name: "Confirm simulated Practice order" });
    expect(back).toHaveFocus();

    await user.tab();
    expect(confirm).toHaveFocus();
    await user.keyboard("{Enter}");
    expect(onConfirm).toHaveBeenCalledTimes(1);

    await user.tab();
    expect(back).toHaveFocus();
  });

  it("treats Escape as Back and never as confirmation", async () => {
    const user = userEvent.setup();
    const onBack = vi.fn();
    const onConfirm = vi.fn();
    render(
      <PracticeOrderReviewStage
        review={review}
        confirming={false}
        onBack={onBack}
        onConfirm={onConfirm}
      />,
    );

    await user.keyboard("{Escape}");

    expect(onBack).toHaveBeenCalledTimes(1);
    expect(onConfirm).not.toHaveBeenCalled();
  });

  it("disables both actions while one confirmation is in flight", () => {
    render(
      <PracticeOrderReviewStage
        review={review}
        confirming
        onBack={vi.fn()}
        onConfirm={vi.fn()}
      />,
    );

    expect(screen.getByRole("button", { name: "Back to edit" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Confirm simulated Practice order" }))
      .toHaveAttribute("aria-busy", "true");
  });
});
