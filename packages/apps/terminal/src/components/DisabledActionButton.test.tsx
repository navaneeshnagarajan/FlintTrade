import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { DisabledActionButton, DisabledReason } from "./DisabledActionButton";

describe("DisabledReason", () => {
  it("puts the reason on a span that Tab reaches, and shows it on focus", async () => {
    const user = userEvent.setup();
    render(
      <DisabledReason reason="Order sent. Waiting for reply.">
        <button type="button" disabled>Buy</button>
      </DisabledReason>,
    );

    await user.tab();

    const trigger = screen.getByText("Buy").parentElement as HTMLElement;
    expect(trigger).toHaveFocus();
    expect(await screen.findByRole("tooltip")).toHaveTextContent("Order sent. Waiting for reply.");
  });

  it("adds no tab stop and no tooltip without a reason", async () => {
    const user = userEvent.setup();
    render(
      <DisabledReason reason={null}>
        <button type="button">Buy</button>
      </DisabledReason>,
    );

    await user.tab();

    expect(screen.getByRole("button", { name: "Buy" })).toHaveFocus();
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
  });

  it("keeps the same button element when the reason appears and clears", () => {
    const { rerender } = render(
      <DisabledReason reason={null}>
        <button type="button">Buy</button>
      </DisabledReason>,
    );
    const button = screen.getByRole("button", { name: "Buy" });

    rerender(
      <DisabledReason reason="Order sent. Waiting for reply.">
        <button type="button">Buy</button>
      </DisabledReason>,
    );

    expect(screen.getByRole("button", { name: "Buy" })).toBe(button);
  });
});

describe("DisabledActionButton", () => {
  it("shows its tooltip when the span takes focus", async () => {
    const user = userEvent.setup();
    render(<DisabledActionButton label="Add SIP" tooltip="Connect a broker first." />);

    await user.tab();

    expect(await screen.findByRole("tooltip")).toHaveTextContent("Connect a broker first.");
    expect(screen.getByRole("button", { name: "Add SIP" })).toBeDisabled();
  });
});
