/**
 * PracticeLaterSetup — optional work after the Practice affirm.
 *
 * The tray is a one-line reminder until Show. It must not count toward
 * Step N of M, must remember Later across reloads, and must keep
 * "Continue without a broker" ahead of the native and OpenAlgo controls.
 */

import { describe, it, expect, beforeEach } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";

import {
  clearOptionalSetupState,
  clearSessionRecoveryMaterialForTests,
  markPracticeLaterPending,
  OPTIONAL_SETUP_STATE_KEY,
  PRACTICE_LATER_KEY,
  PracticeLaterSetup,
} from "../SetupAccountRoute";

describe("PracticeLaterSetup", () => {
  beforeEach(() => {
    localStorage.clear();
    clearSessionRecoveryMaterialForTests();
    clearOptionalSetupState();
  });

  it("stays hidden until the operator has opened the Practice desk", () => {
    const { container } = render(<PracticeLaterSetup />);
    expect(container).toBeEmptyDOMElement();
    expect(screen.queryByText(/Step \d+ of \d+/)).not.toBeInTheDocument();
  });

  it("collapses to a one-line reminder with Show and Dismiss", () => {
    markPracticeLaterPending();
    render(<PracticeLaterSetup />);

    expect(screen.getByText("Optional setup · 0 of 4 done")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Show" })).toHaveAttribute("aria-expanded", "false");
    expect(screen.getByRole("button", { name: "Dismiss" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Skip Two-factor authentication" })).not.toBeInTheDocument();
    expect(screen.queryByText(/Step \d+ of \d+/)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Set up Monitoring" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Set up Risk" })).not.toBeInTheDocument();
  });

  it("Show expands the four cards in place", () => {
    markPracticeLaterPending();
    render(<PracticeLaterSetup />);
    fireEvent.click(screen.getByRole("button", { name: "Show" }));

    expect(screen.getByRole("button", { name: "Hide" })).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText("Optional setup · 0 of 4 done")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Skip Two-factor authentication" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Continue without a broker" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "FlintTrade Native" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "OpenAlgo Bridge" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Skip LLM" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Skip Trading defaults" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Skip Monitoring" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Skip Risk" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /live/i })).not.toBeInTheDocument();
  });

  it("remembers Later across a reload and counts it on the strip", () => {
    markPracticeLaterPending();
    const first = render(<PracticeLaterSetup />);
    fireEvent.click(screen.getByRole("button", { name: "Show" }));
    fireEvent.click(screen.getByRole("button", { name: "Skip Two-factor authentication" }));
    fireEvent.click(screen.getByRole("button", { name: "Continue without a broker" }));

    expect(screen.getByText("Optional setup · 2 of 4 done")).toBeInTheDocument();
    expect(localStorage.getItem(PRACTICE_LATER_KEY)).toBe("1");
    expect(localStorage.getItem(OPTIONAL_SETUP_STATE_KEY)).toContain("totp");
    first.unmount();

    render(<PracticeLaterSetup />);
    expect(screen.getByText("Optional setup · 2 of 4 done")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Show" }));
    expect(screen.getByText(/Two-factor authentication/)).toHaveTextContent("later");
    expect(screen.getByText(/Broker connect/)).toHaveTextContent("later");
  });

  it("Dismiss moves the reminder into Settings and leaves the desk", () => {
    markPracticeLaterPending();
    const desk = render(<PracticeLaterSetup />);
    fireEvent.click(screen.getByRole("button", { name: "Dismiss" }));
    expect(desk.container).toBeEmptyDOMElement();
    expect(localStorage.getItem(PRACTICE_LATER_KEY)).toBeNull();

    render(<PracticeLaterSetup surface="settings" />);
    expect(screen.getByText("Optional setup · 0 of 4 done")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Dismiss" })).not.toBeInTheDocument();
  });

  it("puts Continue without a broker ahead of native and OpenAlgo", () => {
    markPracticeLaterPending();
    render(<PracticeLaterSetup />);
    fireEvent.click(screen.getByRole("button", { name: "Show" }));
    fireEvent.click(screen.getByRole("button", { name: "Set up Broker connect" }));

    const skipBroker = screen.getByRole("button", { name: "Continue without a broker" });
    const native = screen.getByRole("button", { name: "FlintTrade Native" });
    const openAlgo = screen.getByRole("button", { name: "OpenAlgo Bridge" });
    expect(
      skipBroker.compareDocumentPosition(native) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    expect(
      skipBroker.compareDocumentPosition(openAlgo) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();

    fireEvent.click(skipBroker);
    expect(screen.getByRole("button", { name: "Set up Broker connect" })).toBeInTheDocument();
    expect(screen.queryByText(/Step \d+ of \d+/)).not.toBeInTheDocument();
  });

  it("2FA card offers Enrol and Later only", () => {
    markPracticeLaterPending();
    render(<PracticeLaterSetup />);
    fireEvent.click(screen.getByRole("button", { name: "Show" }));
    fireEvent.click(screen.getByRole("button", { name: "Set up Two-factor authentication" }));

    expect(screen.getByRole("button", { name: "Enrol" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Later" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /delete account/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /reset 2FA/i })).not.toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent(/not retained/i);

    fireEvent.click(screen.getByRole("button", { name: "Later" }));
    expect(screen.getByRole("button", { name: "Set up Two-factor authentication" })).toBeInTheDocument();
    expect(screen.getByText("Optional setup · 1 of 4 done")).toBeInTheDocument();
  });

  it("Enrol without a stored QR asks for the account password", () => {
    markPracticeLaterPending();
    render(<PracticeLaterSetup />);
    fireEvent.click(screen.getByRole("button", { name: "Show" }));
    fireEvent.click(screen.getByRole("button", { name: "Set up Two-factor authentication" }));
    fireEvent.click(screen.getByRole("button", { name: "Enrol" }));

    expect(screen.getByLabelText("Confirm password")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Enrol" })).toBeDisabled();
    expect(screen.queryByRole("button", { name: /delete account/i })).not.toBeInTheDocument();
  });

  it("keeps trading defaults behind Later on the desk", () => {
    markPracticeLaterPending();
    render(<PracticeLaterSetup />);
    fireEvent.click(screen.getByRole("button", { name: "Show" }));

    expect(screen.queryByLabelText("Position lot reference")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Set up Trading defaults" }));
    expect(screen.getByText("Default Exchange")).toBeInTheDocument();
    expect(screen.queryByText(/Step \d+ of \d+/)).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Skip Trading defaults" }));
    expect(screen.getByText("Optional setup · 1 of 4 done")).toBeInTheDocument();
  });
});
