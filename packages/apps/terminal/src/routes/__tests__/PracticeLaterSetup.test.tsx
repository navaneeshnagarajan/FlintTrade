/**
 * PracticeLaterSetup — optional work after the Practice affirm.
 *
 * The tray is a one-line reminder until Show. It must not count toward
 * Step N of M, must remember Later across reloads, and must keep
 * "Continue without a broker" ahead of the native and broker controls.
 */

import { describe, it, expect, beforeEach } from "vitest";
import { fireEvent, render, screen, within } from "@testing-library/react";
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
    const show = screen.getByRole("button", { name: "Show" });
    expect(show).toHaveAttribute("aria-expanded", "false");
    expect(show.className).toContain("w-16");
    expect(show.className.split(/\s+/)).toContain("text-text-primary");
    expect(show.className.split(/\s+/)).not.toContain("text-text-secondary");
    const dismiss = screen.getByRole("button", { name: "Dismiss" });
    expect(dismiss.className.split(/\s+/)).toContain("text-text-primary");
    expect(dismiss.className.split(/\s+/)).not.toContain("text-text-secondary");
    expect(screen.queryByRole("button", { name: "Later Two-factor authentication" })).not.toBeInTheDocument();
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
    expect(screen.getByRole("button", { name: "Hide" }).className).toContain("w-16");
    const laterTotp = screen.getByRole("button", { name: "Later Two-factor authentication" });
    expect(laterTotp).toHaveTextContent("Later");
    expect(screen.getByRole("button", { name: "Later LLM" })).toHaveTextContent("Later");
    expect(screen.getByRole("button", { name: "Later Trading defaults" })).toHaveTextContent("Later");
    expect(screen.getByRole("button", { name: "Continue without a broker" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "FlintTrade Native" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "native broker Bridge" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Later Monitoring" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Later Risk" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /live/i })).not.toBeInTheDocument();
  });

  it("remembers Later across a reload and counts it on the strip", () => {
    markPracticeLaterPending();
    const first = render(<PracticeLaterSetup />);
    fireEvent.click(screen.getByRole("button", { name: "Show" }));
    fireEvent.click(screen.getByRole("button", { name: "Later Two-factor authentication" }));
    fireEvent.click(screen.getByRole("button", { name: "Continue without a broker" }));

    expect(screen.getByText("Optional setup · 0 of 4 done · 2 skipped")).toBeInTheDocument();
    expect(localStorage.getItem(PRACTICE_LATER_KEY)).toBe("1");
    expect(localStorage.getItem(OPTIONAL_SETUP_STATE_KEY)).toContain("totp");
    first.unmount();

    render(<PracticeLaterSetup />);
    expect(screen.getByText("Optional setup · 0 of 4 done · 2 skipped")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Show" }));
    for (const title of ["Two-factor authentication", "Broker connect"]) {
      const card = screen.getByText(title).closest("li");
      expect(card).not.toBeNull();
      const view = within(card as HTMLElement);
      expect(view.getByText(title)).toHaveTextContent(title);
      expect(view.getByText(title).textContent).not.toMatch(/later/i);
      expect(view.getByText("Skipped")).toBeInTheDocument();
      expect(view.getAllByRole("button").map((button) => button.textContent)).toEqual(["Set up"]);
    }
    expect(screen.queryByRole("button", { name: "Later Two-factor authentication" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Continue without a broker" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Set up Two-factor authentication" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Set up Broker connect" })).toBeInTheDocument();
  });

  it("Dismiss moves the reminder into Settings and leaves the desk", () => {
    markPracticeLaterPending();
    const desk = render(<PracticeLaterSetup />);
    fireEvent.click(screen.getByRole("button", { name: "Dismiss" }));
    expect(desk.container).toBeEmptyDOMElement();
    expect(localStorage.getItem(PRACTICE_LATER_KEY)).toBeNull();

    render(<PracticeLaterSetup surface="settings" />);
    expect(screen.getByText("Optional setup · 0 of 4 done")).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Optional setup" }).className).toContain("mb-4");
    expect(screen.queryByRole("button", { name: "Dismiss" })).not.toBeInTheDocument();
  });

  it("puts brokerless Practice before the optional native connection", () => {
    markPracticeLaterPending();
    render(<PracticeLaterSetup />);
    fireEvent.click(screen.getByRole("button", { name: "Show" }));
    fireEvent.click(screen.getByRole("button", { name: "Set up Broker connect" }));

    const skipBroker = screen.getByRole("button", { name: "Continue without a broker" });
    const native = screen.getByRole("button", { name: "FlintTrade Native" });
    expect(screen.getAllByRole("button", { name: /flinttrade native/i })).toHaveLength(1);
    expect(
      skipBroker.compareDocumentPosition(native) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();

    fireEvent.click(skipBroker);
    expect(screen.getByRole("button", { name: "Set up Broker connect" })).toBeInTheDocument();
    expect(screen.queryByText(/Step \d+ of \d+/)).not.toBeInTheDocument();
    expect(screen.getByText("Optional setup · 0 of 4 done · 1 skipped")).toBeInTheDocument();
  });

  it("records Continue without a broker on the open panel as skipped", () => {
    markPracticeLaterPending();
    render(<PracticeLaterSetup />);
    expect(screen.getByText("Optional setup · 0 of 4 done")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Show" }));
    fireEvent.click(screen.getByRole("button", { name: "Set up Broker connect" }));
    fireEvent.click(screen.getByRole("button", { name: "Continue without a broker" }));

    expect(screen.getByText("Optional setup · 0 of 4 done · 1 skipped")).toBeInTheDocument();
    const card = screen.getByText("Broker connect").closest("li");
    expect(card).not.toBeNull();
    const view = within(card as HTMLElement);
    expect(view.getByText("Skipped")).toBeInTheDocument();
    expect(view.queryByText("Done")).not.toBeInTheDocument();
    expect(view.queryByRole("button", { name: "Continue without a broker" })).not.toBeInTheDocument();
    expect(view.getAllByRole("button").map((button) => button.textContent)).toEqual(["Set up"]);
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
    expect(screen.getByRole("button", { name: "Later Two-factor authentication" })).toBeInTheDocument();
    expect(screen.getByText("Optional setup · 0 of 4 done")).toBeInTheDocument();
    expect(screen.queryByText("Skipped")).not.toBeInTheDocument();
    expect(screen.queryByText("Done")).not.toBeInTheDocument();
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

    fireEvent.click(screen.getByRole("button", { name: "Later Trading defaults" }));
    expect(screen.getByText("Optional setup · 0 of 4 done")).toBeInTheDocument();
    expect(screen.queryByText("Skipped")).not.toBeInTheDocument();
    expect(screen.queryByText("Done")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Later Trading defaults" }));
    expect(screen.getByText("Optional setup · 0 of 4 done · 1 skipped")).toBeInTheDocument();
    const trading = screen.getByText("Trading defaults").closest("li");
    expect(trading).not.toBeNull();
    const tradingView = within(trading as HTMLElement);
    expect(tradingView.getByText("Trading defaults").textContent).not.toMatch(/later/i);
    expect(tradingView.getByText("Skipped")).toBeInTheDocument();
    expect(tradingView.getAllByRole("button").map((button) => button.textContent)).toEqual(["Set up"]);
    expect(screen.queryByRole("button", { name: "Later Trading defaults" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Set up Trading defaults" })).toBeInTheDocument();
  });

  it("hides Continue without a broker on a finished Broker card", () => {
    localStorage.setItem(OPTIONAL_SETUP_STATE_KEY, JSON.stringify({
      skipped: [],
      completed: ["broker"],
      dismissed: false,
    }));
    markPracticeLaterPending();
    render(<PracticeLaterSetup />);
    fireEvent.click(screen.getByRole("button", { name: "Show" }));

    const card = screen.getByText("Broker connect").closest("li");
    expect(card).not.toBeNull();
    const view = within(card as HTMLElement);
    expect(view.getByText("Done")).toBeInTheDocument();
    expect(view.queryByRole("button", { name: "Continue without a broker" })).not.toBeInTheDocument();
    expect(view.queryByRole("button", { name: /later/i })).not.toBeInTheDocument();
    expect(view.getAllByRole("button").map((button) => button.textContent)).toEqual(["Set up"]);
  });

  it("keeps Continue without a broker on a Broker card that is not done", () => {
    markPracticeLaterPending();
    render(<PracticeLaterSetup />);
    fireEvent.click(screen.getByRole("button", { name: "Show" }));

    const card = screen.getByText("Broker connect").closest("li");
    expect(card).not.toBeNull();
    const view = within(card as HTMLElement);
    expect(view.queryByText("Done")).not.toBeInTheDocument();
    expect(view.queryByText("Skipped")).not.toBeInTheDocument();
    expect(view.getByRole("button", { name: "Continue without a broker" })).toBeInTheDocument();
    expect(view.getByRole("button", { name: "Set up Broker connect" })).toBeInTheDocument();
  });

  it("Later inside a panel closes it and leaves the card and strip unchanged", () => {
    const panels = [
      {
        id: "totp",
        open: "Set up Two-factor authentication",
        later: "Later",
        title: "Two-factor authentication",
      },
      {
        id: "llm",
        open: "Set up LLM",
        later: "Later LLM",
        title: "LLM",
      },
      {
        id: "trading",
        open: "Set up Trading defaults",
        later: "Later Trading defaults",
        title: "Trading defaults",
      },
    ] as const;

    for (const panel of panels) {
      for (const started of ["not-started", "done"] as const) {
        localStorage.clear();
        clearOptionalSetupState();
        const state = {
          skipped: ["broker"],
          completed: started === "done" ? [panel.id] : [],
          dismissed: false,
        };
        localStorage.setItem(OPTIONAL_SETUP_STATE_KEY, JSON.stringify(state));
        markPracticeLaterPending();
        const strip = started === "done"
          ? "Optional setup · 1 of 4 done · 1 skipped"
          : "Optional setup · 0 of 4 done · 1 skipped";
        const view = render(<PracticeLaterSetup />);
        fireEvent.click(screen.getByRole("button", { name: "Show" }));
        expect(screen.getByText(strip)).toBeInTheDocument();

        fireEvent.click(screen.getByRole("button", { name: panel.open }));
        fireEvent.click(screen.getByRole("button", { name: panel.later }));

        expect(screen.getByRole("button", { name: panel.open })).toBeInTheDocument();
        expect(screen.getByText(strip)).toBeInTheDocument();
        const card = screen.getByText(panel.title).closest("li");
        expect(card).not.toBeNull();
        const cardView = within(card as HTMLElement);
        if (started === "done") {
          expect(cardView.getByText("Done")).toBeInTheDocument();
          expect(cardView.queryByText("Skipped")).not.toBeInTheDocument();
        } else {
          expect(cardView.queryByText("Done")).not.toBeInTheDocument();
          expect(cardView.queryByText("Skipped")).not.toBeInTheDocument();
        }
        const broker = screen.getByText("Broker connect").closest("li");
        expect(broker).not.toBeNull();
        expect(within(broker as HTMLElement).getByText("Skipped")).toBeInTheDocument();
        expect(JSON.parse(localStorage.getItem(OPTIONAL_SETUP_STATE_KEY) ?? "{}")).toEqual(state);
        view.unmount();
      }
    }
  });

  it("keeps the Skipped and Done tags at text-xxs", () => {
    localStorage.setItem(OPTIONAL_SETUP_STATE_KEY, JSON.stringify({
      skipped: ["totp"],
      completed: ["llm"],
      dismissed: false,
    }));
    markPracticeLaterPending();
    render(<PracticeLaterSetup />);
    fireEvent.click(screen.getByRole("button", { name: "Show" }));

    const skipped = screen.getByText("Skipped");
    const done = screen.getByText("Done");
    expect(skipped).toHaveClass("text-xxs");
    expect(skipped).not.toHaveClass("text-xs");
    expect(done).toHaveClass("text-xxs");
    expect(done).not.toHaveClass("text-xs");
  });

  it("marks a finished card Done and does not offer Later", () => {
    localStorage.setItem(OPTIONAL_SETUP_STATE_KEY, JSON.stringify({
      skipped: [],
      completed: ["llm"],
      dismissed: false,
    }));
    markPracticeLaterPending();
    render(<PracticeLaterSetup />);
    fireEvent.click(screen.getByRole("button", { name: "Show" }));

    const card = screen.getByText("LLM").closest("li");
    expect(card).not.toBeNull();
    const view = within(card as HTMLElement);
    expect(view.getByText("LLM").textContent).toBe("LLM");
    expect(view.getByText("Done")).toBeInTheDocument();
    expect(view.queryByRole("button", { name: "Later LLM" })).not.toBeInTheDocument();
    expect(view.queryByText("Later")).not.toBeInTheDocument();
    expect(view.getByRole("button", { name: "Set up LLM" })).toBeInTheDocument();
  });
});
