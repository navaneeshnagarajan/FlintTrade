import { beforeEach, describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";

import { ExampleDataBadge } from "./ExampleDataBadge";
import { useModeStore } from "@/stores/modeStore";

describe("ExampleDataBadge", () => {
  beforeEach(() => {
    useModeStore.setState({ mode: "explore" });
  });

  it("stays hidden in Explore, where the Mode line already says it", () => {
    render(<ExampleDataBadge />);
    expect(screen.queryByTestId("example-data-badge")).not.toBeInTheDocument();
  });

  it("labels example figures in Practice", () => {
    useModeStore.setState({ mode: "practice" });
    render(<ExampleDataBadge />);
    const badge = screen.getByTestId("example-data-badge");
    expect(badge).toHaveTextContent("Example data");
    expect(badge).toHaveAttribute("role", "status");
    expect(badge).toHaveAttribute(
      "title",
      "These figures are built-in examples, not market or account data.",
    );
  });

  it("labels example figures in Live", () => {
    useModeStore.setState({ mode: "live" });
    render(<ExampleDataBadge />);
    expect(screen.getByTestId("example-data-badge")).toHaveTextContent("Example data");
  });

  it("accepts a custom label and merges a class name", () => {
    useModeStore.setState({ mode: "practice" });
    render(<ExampleDataBadge label="Example rows" className="ml-auto" />);
    const badge = screen.getByTestId("example-data-badge");
    expect(badge).toHaveTextContent("Example rows");
    expect(badge).toHaveClass("ml-auto");
    expect(badge).toHaveClass("text-xxs");
  });
});
