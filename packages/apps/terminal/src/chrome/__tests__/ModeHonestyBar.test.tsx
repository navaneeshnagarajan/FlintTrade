import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";
import ModeHonestyBar from "../ModeHonestyBar";

describe("ModeHonestyBar", () => {
  it("renders the Explore line as one static Mode row", () => {
    render(<ModeHonestyBar mode="explore" />);
    const bar = screen.getByTestId("mode-honesty-bar");
    expect(bar).toHaveAttribute("data-mode", "explore");
    expect(bar).toHaveTextContent(
      "Explore — sample data only. No broker session, no live orders.",
    );
    expect(bar.querySelector("p")).toHaveClass("whitespace-nowrap");
    expect(bar).not.toHaveAttribute("role", "alert");
  });

  it("renders the Practice line", () => {
    render(<ModeHonestyBar mode="practice" />);
    expect(screen.getByTestId("mode-honesty-bar")).toHaveTextContent(
      "Practice — SandboxEngine fills. Not your funded broker account.",
    );
  });

  it("renders the Live line", () => {
    render(<ModeHonestyBar mode="live" />);
    expect(screen.getByTestId("mode-honesty-bar")).toHaveTextContent(
      "Live — real broker session. Orders and money move for real.",
    );
  });
});
