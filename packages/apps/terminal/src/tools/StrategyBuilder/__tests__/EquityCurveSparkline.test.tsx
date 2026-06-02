import { render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";
import { describe, expect, it } from "vitest";

import { EquityCurveSparkline } from "../EquityCurveSparkline";

describe("EquityCurveSparkline", () => {
  it("renders the strategy equity curve through the shared Flint baseline primitive", () => {
    render(
      <EquityCurveSparkline
        curve={[
          { bar: 1, equity: 10000 },
          { bar: 2, equity: 10120 },
          { bar: 3, equity: 10080 },
          { bar: 4, equity: 10250 },
        ]}
      />,
    );

    const sparkline = screen.getByRole("img", { name: "Strategy equity curve" });
    expect(sparkline).toHaveAttribute("viewBox", "0 0 160 42");
    expect(sparkline.querySelector("polyline")).not.toBeInTheDocument();
    expect(sparkline.querySelector("line")).toBeInTheDocument();
    expect(sparkline.querySelectorAll("path").length).toBeGreaterThan(0);
  });
});
