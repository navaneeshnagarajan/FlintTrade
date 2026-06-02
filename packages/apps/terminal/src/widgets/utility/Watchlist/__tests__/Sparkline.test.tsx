import { render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";
import { describe, expect, it } from "vitest";

import { Sparkline } from "../Sparkline";

describe("Watchlist Sparkline", () => {
  it("renders the shared Flint mini sparkline for price history", () => {
    render(<Sparkline prices={[100, 102, 101, 105]} positive />);

    const sparkline = screen.getByRole("img", { name: "Watchlist price trend: rising" });
    expect(sparkline).toHaveAttribute("viewBox", "0 0 160 42");
    expect(sparkline.querySelector("polyline")).not.toBeInTheDocument();
    expect(sparkline.querySelectorAll("path").length).toBeGreaterThan(0);
  });

  it("keeps the compact neutral fallback when there is not enough price history", () => {
    const { container } = render(<Sparkline prices={[100]} positive={null} />);

    expect(container.querySelector("svg")).not.toBeInTheDocument();
    expect(screen.getByText("—")).toBeInTheDocument();
  });
});
