import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { ORDER_STATUS_UNKNOWN } from "@/lib/operatorIncident";
import { tabTo } from "@/test-utils/tabTo";
import { OrderStatusUnknownLine, OrderStatusUnknownTight } from "./OrderStatusUnknownLine";

describe("OrderStatusUnknownTight", () => {
  it("separates the label from Open Orders with a gap and a real space", () => {
    render(<OrderStatusUnknownTight />);
    const line = screen.getByRole("status");

    expect(line).toHaveClass("gap-1");
    expect(line).not.toHaveClass("gap-0");
    expect(line.textContent?.startsWith("Status unknown Open Orders")).toBe(true);
  });

  it("keeps the approved sentence as the tooltip and description", () => {
    render(<OrderStatusUnknownTight />);

    expect(screen.getByRole("status")).toHaveAttribute("title", ORDER_STATUS_UNKNOWN);
    expect(screen.getByRole("button", { name: "Open Orders" })).toHaveAccessibleDescription(ORDER_STATUS_UNKNOWN);
  });
});

describe("OrderStatusUnknownLine clipped", () => {
  it("truncates the sentence on one row and carries it in a tooltip the keyboard reaches", async () => {
    const user = userEvent.setup();
    render(<OrderStatusUnknownLine clip />);
    const sentence = screen.getByText(ORDER_STATUS_UNKNOWN);

    expect(sentence).toHaveClass("truncate");
    expect(screen.getByRole("button", { name: "Open Orders" })).toHaveClass("shrink-0");
    await tabTo(user, sentence);
    expect(await screen.findByRole("tooltip")).toHaveTextContent(ORDER_STATUS_UNKNOWN);
  });

  it("keeps the sentence unclipped by default", () => {
    render(<OrderStatusUnknownLine />);

    expect(screen.getByText(ORDER_STATUS_UNKNOWN)).not.toHaveClass("truncate");
    expect(screen.getByText(ORDER_STATUS_UNKNOWN)).not.toHaveAttribute("tabindex");
  });
});
