import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ORDER_STATUS_UNKNOWN } from "@/lib/operatorIncident";
import { OrderStatusUnknownTight } from "./OrderStatusUnknownLine";

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
