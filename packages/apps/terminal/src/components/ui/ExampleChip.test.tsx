import { beforeEach, describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";

import { ExampleChip } from "./ExampleChip";
import { useModeStore } from "@/stores/modeStore";

describe("ExampleChip", () => {
  beforeEach(() => {
    useModeStore.setState({ mode: "explore" });
  });

  it("marks example data with one Example chip", () => {
    render(<ExampleChip />);
    const chip = screen.getByTestId("example-chip");
    expect(chip).toHaveTextContent("Example");
    expect(chip).toHaveAttribute("aria-label", "Example");
    expect(screen.queryByText(/Connect a broker to see your own/)).not.toBeInTheDocument();
  });

  it("does not show in Practice", () => {
    useModeStore.setState({ mode: "practice" });
    render(<ExampleChip />);
    expect(screen.queryByTestId("example-chip")).not.toBeInTheDocument();
  });

  it("does not show in Live", () => {
    useModeStore.setState({ mode: "live" });
    render(<ExampleChip />);
    expect(screen.queryByTestId("example-chip")).not.toBeInTheDocument();
  });
});
