import { render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";
import { describe, expect, it } from "vitest";

import { MiniChartCard } from "../MiniChartCard";

describe("MiniChartCard", () => {
  it("renders the NIFTY sparkline through the shared Flint primitive", () => {
    render(<MiniChartCard />);

    const sparkline = screen.getByRole("img", { name: "NIFTY 50 1D sparkline" });
    expect(sparkline).toHaveAttribute("viewBox", "0 0 160 42");
    expect(sparkline.querySelector("polyline")).not.toBeInTheDocument();
    expect(sparkline.querySelectorAll("path").length).toBeGreaterThan(0);
  });
});
