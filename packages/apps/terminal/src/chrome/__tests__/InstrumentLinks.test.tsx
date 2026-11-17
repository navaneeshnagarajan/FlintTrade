import { afterEach, describe, expect, it } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";

import { InstrumentLinks } from "../InstrumentLinks";

afterEach(cleanup);

describe("InstrumentLinks", () => {
  it("keeps the link controls mounted behind one toolbar toggle", () => {
    render(<InstrumentLinks app="terminal" />);
    const toggle = screen.getByRole("button", { name: "Instrument links · Unlinked" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    // Mounted, so a channel choice and a typed symbol survive closing the panel.
    const channel = screen.getByLabelText("Instrument link channel");
    expect(channel).not.toBeVisible();
    expect(screen.queryByRole("combobox", { name: "Instrument link channel" })).not.toBeInTheDocument();

    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("combobox", { name: "Instrument link channel" })).toBe(channel);
    expect(channel).toBeVisible();
    fireEvent.change(screen.getByLabelText("Linked symbol"), { target: { value: "SBIN" } });

    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(screen.getByLabelText("Linked symbol")).toHaveValue("SBIN");
  });

  it("says in the toggle's name when a channel is linked", () => {
    render(<InstrumentLinks app="terminal" />);
    fireEvent.click(screen.getByRole("button", { name: "Instrument links · Unlinked" }));
    const channel = screen.getByRole("combobox", { name: "Instrument link channel" });
    const firstChannel = (channel.querySelectorAll("option")[1] as HTMLOptionElement).value;
    fireEvent.change(channel, { target: { value: firstChannel } });
    expect(screen.getByRole("button", { name: "Instrument links · Linked selections only" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Broadcast selection" })).toBeDisabled();
  });
});
