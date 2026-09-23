/**
 * PracticeLaterSetup — optional work after the Practice affirm.
 *
 * The tray must not count toward Step N of M, must not leave the desk
 * when a panel is skipped, and must keep "Continue without a broker"
 * ahead of the native and OpenAlgo controls.
 */

import { describe, it, expect, beforeEach } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";

import {
  clearPracticeLaterPending,
  clearSessionRecoveryMaterialForTests,
  markPracticeLaterPending,
  PRACTICE_LATER_KEY,
  PracticeLaterSetup,
} from "../SetupAccountRoute";

describe("PracticeLaterSetup", () => {
  beforeEach(() => {
    localStorage.clear();
    clearSessionRecoveryMaterialForTests();
    clearPracticeLaterPending();
  });

  it("stays hidden until the operator has opened the Practice desk", () => {
    const { container } = render(<PracticeLaterSetup />);
    expect(container).toBeEmptyDOMElement();
    expect(screen.queryByText(/Step \d+ of \d+/)).not.toBeInTheDocument();
  });

  it("offers Later and Skip without a required-step fraction", () => {
    markPracticeLaterPending();
    render(<PracticeLaterSetup />);

    expect(screen.getByText("Optional")).toBeInTheDocument();
    expect(screen.queryByText(/Step \d+ of \d+/)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Skip Two-factor authentication" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Skip Broker connect" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Skip LLM" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Skip Monitoring" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Skip Trading defaults" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Skip Risk" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /live/i })).not.toBeInTheDocument();
  });

  it("skipping optional setup leaves the operator on the Practice desk", () => {
    markPracticeLaterPending();
    render(<PracticeLaterSetup />);

    for (const name of [
      "Skip Two-factor authentication",
      "Skip Broker connect",
      "Skip LLM",
      "Skip Monitoring",
    ]) {
      fireEvent.click(screen.getByRole("button", { name }));
    }

    expect(screen.getByRole("button", { name: "Set up Broker connect" })).toBeInTheDocument();
    expect(screen.queryByText(/Step \d+ of \d+/)).not.toBeInTheDocument();
    expect(localStorage.getItem(PRACTICE_LATER_KEY)).toBe("1");
  });

  it("puts Continue without a broker ahead of native and OpenAlgo", () => {
    markPracticeLaterPending();
    render(<PracticeLaterSetup />);
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

  it("hides the required-step fraction while Monitoring is open", () => {
    markPracticeLaterPending();
    render(<PracticeLaterSetup />);
    fireEvent.click(screen.getByRole("button", { name: "Set up Monitoring" }));

    expect(screen.getByText("Optional")).toBeInTheDocument();
    expect(screen.queryByText(/Step \d+ of \d+/)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Skip Monitoring" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Skip Monitoring" }));
    expect(screen.getByRole("button", { name: "Set up Monitoring" })).toBeInTheDocument();
  });

  it("Set up later on the authenticator stays on the desk without enabling 2FA", () => {
    markPracticeLaterPending();
    render(<PracticeLaterSetup />);
    fireEvent.click(screen.getByRole("button", { name: "Set up Two-factor authentication" }));
    fireEvent.click(screen.getByRole("button", { name: /set up later/i }));

    expect(screen.getByRole("button", { name: "Set up Two-factor authentication" })).toBeInTheDocument();
    expect(screen.queryByText(/Step \d+ of \d+/)).not.toBeInTheDocument();
    expect(localStorage.getItem(PRACTICE_LATER_KEY)).toBe("1");
  });

  it("requires password-backed 2FA regeneration when the QR seed was not kept", () => {
    markPracticeLaterPending();
    render(<PracticeLaterSetup />);
    fireEvent.click(screen.getByRole("button", { name: "Set up Two-factor authentication" }));

    expect(screen.getByRole("alert")).toHaveTextContent(/not retained/i);
    expect(screen.getByRole("button", { name: /show QR code/i })).toBeDisabled();
    expect(screen.getByRole("button", { name: /reset 2FA/i })).toBeEnabled();
    expect(screen.getByRole("button", { name: /delete account/i })).toBeInTheDocument();
  });

  it("keeps trading defaults and risk behind Later on the desk", () => {
    markPracticeLaterPending();
    render(<PracticeLaterSetup />);

    expect(screen.queryByLabelText("Position lot reference")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Set up Trading defaults" }));
    expect(screen.getByText("Default Exchange")).toBeInTheDocument();
    expect(screen.queryByText(/Step \d+ of \d+/)).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Skip Trading defaults" }));
    fireEvent.click(screen.getByRole("button", { name: "Set up Risk" }));
    expect(screen.getByLabelText("Position lot reference")).toBeInTheDocument();
    expect(screen.queryByText(/Step \d+ of \d+/)).not.toBeInTheDocument();
  });
});
