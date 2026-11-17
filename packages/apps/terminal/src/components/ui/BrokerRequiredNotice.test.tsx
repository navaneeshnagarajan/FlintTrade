import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";

import { BrokerRequiredNotice, isBrokerRequiredMessage } from "./BrokerRequiredNotice";

describe("isBrokerRequiredMessage", () => {
  it("matches the backend's broker-required refusal in any casing", () => {
    expect(isBrokerRequiredMessage("A connected native broker account is required for optionchain.")).toBe(true);
    expect(isBrokerRequiredMessage("a CONNECTED NATIVE BROKER ACCOUNT IS REQUIRED.")).toBe(true);
  });

  it("reads the message of an Error", () => {
    expect(isBrokerRequiredMessage(new Error("A connected native broker account is required for expiry."))).toBe(true);
  });

  it("rejects other errors and non-text values", () => {
    expect(isBrokerRequiredMessage("Failed to load option chain")).toBe(false);
    expect(isBrokerRequiredMessage("Broker session expired")).toBe(false);
    expect(isBrokerRequiredMessage("")).toBe(false);
    expect(isBrokerRequiredMessage(null)).toBe(false);
    expect(isBrokerRequiredMessage(undefined)).toBe(false);
    expect(isBrokerRequiredMessage(404)).toBe(false);
    expect(isBrokerRequiredMessage({ message: "A connected native broker account is required." })).toBe(false);
  });
});

describe("BrokerRequiredNotice", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders a neutral one-line prompt naming what a broker would load", () => {
    render(<BrokerRequiredNotice what="the option chain" />);

    const notice = screen.getByTestId("broker-required-notice");
    expect(notice).toHaveTextContent("Connect a broker to load the option chain.");
    expect(notice).toHaveAttribute("data-tone", "neutral");
    expect(notice).toHaveAttribute("role", "note");
    expect(notice.className).not.toMatch(/text-loss|bg-loss|border-loss/);
  });

  it("opens the Brokers page through the terminal's navigate event", () => {
    const dispatched: Event[] = [];
    const listener = (event: Event) => dispatched.push(event);
    window.addEventListener("flinttrade:navigate", listener);

    render(<BrokerRequiredNotice what="expiries" />);
    fireEvent.click(screen.getByRole("button", { name: "Open Brokers" }));

    window.removeEventListener("flinttrade:navigate", listener);
    expect(dispatched).toHaveLength(1);
    expect((dispatched[0] as CustomEvent<string>).detail).toBe("/brokers");
  });

  it("merges a caller className", () => {
    render(<BrokerRequiredNotice what="pivots" className="ml-auto" />);
    expect(screen.getByTestId("broker-required-notice")).toHaveClass("ml-auto");
  });
});
