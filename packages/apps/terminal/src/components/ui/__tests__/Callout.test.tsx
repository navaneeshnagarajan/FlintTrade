import { describe, it, expect, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";
import { Callout } from "../Callout";
import { EmptyState, ErrorState, LoadingState } from "../states";

describe("Callout", () => {
  it("renders a note with title, copy and action", () => {
    render(
      <Callout tone="warning" title="Sample data" action={<button type="button">Connect</button>}>
        Connect a broker to see your own holdings.
      </Callout>,
    );
    const note = screen.getByRole("note");
    expect(note).toHaveAttribute("data-tone", "warning");
    expect(screen.getByText("Sample data")).toBeInTheDocument();
    expect(screen.getByText("Connect a broker to see your own holdings.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Connect" })).toBeInTheDocument();
  });

  it("offers a labelled dismiss button only when dismissible", () => {
    const onDismiss = vi.fn();
    const { rerender } = render(<Callout>Tip</Callout>);
    expect(screen.queryByRole("button")).not.toBeInTheDocument();

    rerender(
      <Callout onDismiss={onDismiss} dismissLabel="Dismiss hint">
        Tip
      </Callout>,
    );
    fireEvent.click(screen.getByRole("button", { name: "Dismiss hint" }));
    expect(onDismiss).toHaveBeenCalledTimes(1);
  });

  it("keeps copy on readable text tokens for every tone", () => {
    render(<Callout tone="danger">Kill switch active</Callout>);
    expect(screen.getByText("Kill switch active").className).toContain("text-text-secondary");
  });
});

describe("shared states", () => {
  it("EmptyState shows title, help and actions", () => {
    render(
      <EmptyState
        title="No strategies running"
        description="Start one from the Strategy Builder."
        action={<button type="button">Open Strategy Builder</button>}
      />,
    );
    expect(screen.getByText("No strategies running")).toBeInTheDocument();
    expect(screen.getByText("Start one from the Strategy Builder.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Open Strategy Builder" })).toBeInTheDocument();
  });

  it("LoadingState announces politely", () => {
    render(<LoadingState label="Loading holdings…" />);
    const status = screen.getByRole("status");
    expect(status).toHaveAttribute("aria-live", "polite");
    expect(status).toHaveTextContent("Loading holdings…");
  });

  it("ErrorState only interrupts when asked to", () => {
    const { rerender } = render(<ErrorState title="Page unavailable" />);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    rerender(<ErrorState title="Page unavailable" alert />);
    expect(screen.getByRole("alert")).toHaveTextContent("Page unavailable");
  });
});
