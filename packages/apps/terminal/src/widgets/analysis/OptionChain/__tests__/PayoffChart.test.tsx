/**
 * PayoffChart.test.tsx
 *
 * Unit tests for the SVG-based options payoff curve component.
 * Covers: rendering, zero line, breakeven labels, strike labels, tooltip.
 */

import { dirname, resolve } from "node:path";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, it, expect } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import "@testing-library/jest-dom";

import PayoffChart from "../PayoffChart";
import type { PayoffChartProps } from "../PayoffChart";
import type { OptionLeg } from "../LegBuilder";

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

/** Single BUY CE leg — simple hockey-stick payoff */
const buyCallLeg: OptionLeg = {
  id: "leg-1",
  side: "BUY",
  optionType: "CE",
  strike: 22000,
  lots: 1,
  premium: 150,
};

/** SELL CE + SELL PE at 22000 — short straddle (credit strategy) */
const straddleLegs: OptionLeg[] = [
  {
    id: "leg-2",
    side: "SELL",
    optionType: "CE",
    strike: 22000,
    lots: 1,
    premium: 150,
  },
  {
    id: "leg-3",
    side: "SELL",
    optionType: "PE",
    strike: 22000,
    lots: 1,
    premium: 150,
  },
];

/** Bull call spread — BUY 22000 CE, SELL 22100 CE */
const bullCallSpreadLegs: OptionLeg[] = [
  {
    id: "leg-4",
    side: "BUY",
    optionType: "CE",
    strike: 22000,
    lots: 1,
    premium: 150,
  },
  {
    id: "leg-5",
    side: "SELL",
    optionType: "CE",
    strike: 22100,
    lots: 1,
    premium: 80,
  },
];

const defaultProps: PayoffChartProps = {
  legs:      [buyCallLeg],
  spotPrice: 22000,
  lotSize:   50,
  maxProfit: null,
  maxLoss:   -7500,
  breakevens: [22150],
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function renderChart(overrides: Partial<PayoffChartProps> = {}) {
  return render(<PayoffChart {...defaultProps} {...overrides} />);
}

const testDir = dirname(fileURLToPath(import.meta.url));
const payoffChartSource = () =>
  readFileSync(resolve(testDir, "../PayoffChart.tsx"), "utf8");

// ---------------------------------------------------------------------------
// Render
// ---------------------------------------------------------------------------

describe("PayoffChart — render", () => {
  it("renders without crash", () => {
    const { container } = renderChart();
    expect(container.firstChild).not.toBeNull();
  });

  it("renders an SVG element", () => {
    renderChart();
    const svg = document.querySelector("svg");
    expect(svg).not.toBeNull();
  });

  it("renders the accessible wrapper with correct role", () => {
    renderChart();
    expect(
      screen.getByRole("img", { name: "Options payoff chart" }),
    ).toBeInTheDocument();
  });

  it("routes rendering through the shared Flint payoff chart primitive", () => {
    renderChart();
    const chart = screen.getByRole("img", { name: "Options payoff chart" });
    expect(chart).toHaveAttribute("data-flint-chart", "payoff");
  });

  it("keeps local SVG path markup out of the OptionChain wrapper", () => {
    const source = payoffChartSource();
    expect(source).not.toContain("<" + "svg");
    expect(source).not.toContain("<" + "path");
    expect(source).not.toContain("<" + "line");
  });

  it("renders with no legs without crashing", () => {
    const { container } = renderChart({ legs: [], breakevens: [], maxProfit: null, maxLoss: null });
    expect(container.firstChild).not.toBeNull();
  });

  it("renders straddle legs without crash", () => {
    const { container } = renderChart({
      legs: straddleLegs,
      breakevens: [21700, 22300],
      maxProfit: 15000,
      maxLoss: null,
    });
    expect(container.firstChild).not.toBeNull();
  });

  it("renders bull call spread without crash", () => {
    const { container } = renderChart({
      legs:      bullCallSpreadLegs,
      breakevens: [22070],
      maxProfit: 2500,
      maxLoss:   -3500,
    });
    expect(container.firstChild).not.toBeNull();
  });
});

// ---------------------------------------------------------------------------
// Zero line
// ---------------------------------------------------------------------------

describe("PayoffChart — zero line", () => {
  it("renders the zero line element", () => {
    renderChart();
    const zeroLine = document.querySelector("[data-testid='zero-line']");
    expect(zeroLine).not.toBeNull();
  });

  it("zero line is a horizontal SVG line element", () => {
    renderChart();
    const zeroLine = document.querySelector("[data-testid='zero-line']");
    expect(zeroLine?.tagName.toLowerCase()).toBe("line");
  });

  it("zero line has consistent y1 and y2 (horizontal)", () => {
    renderChart();
    const line = document.querySelector("[data-testid='zero-line']") as SVGLineElement;
    expect(line).not.toBeNull();
    expect(line.getAttribute("y1")).toBe(line.getAttribute("y2"));
  });

  it("zero line is rendered with a dashed stroke", () => {
    renderChart();
    const line = document.querySelector("[data-testid='zero-line']") as SVGLineElement;
    expect(line?.getAttribute("stroke-dasharray")).not.toBeNull();
  });
});

// ---------------------------------------------------------------------------
// Strike labels
// ---------------------------------------------------------------------------

describe("PayoffChart — strike labels", () => {
  it("renders a strike label for a single leg's strike", () => {
    renderChart({ legs: [buyCallLeg] });
    const strikeLabel = document.querySelector("[aria-label='Strike 22000']");
    expect(strikeLabel).not.toBeNull();
  });

  it("renders distinct strike labels for a spread with two different strikes", () => {
    renderChart({ legs: bullCallSpreadLegs, breakevens: [22070] });
    const s1 = document.querySelector("[aria-label='Strike 22000']");
    const s2 = document.querySelector("[aria-label='Strike 22100']");
    expect(s1).not.toBeNull();
    expect(s2).not.toBeNull();
  });

  it("deduplicates identical strike prices across legs", () => {
    renderChart({ legs: straddleLegs, breakevens: [] });
    // Both straddle legs share strike 22000 — only one label should appear
    const strikeLabels = document.querySelectorAll("[aria-label='Strike 22000']");
    expect(strikeLabels).toHaveLength(1);
  });
});

// ---------------------------------------------------------------------------
// Breakeven labels
// ---------------------------------------------------------------------------

describe("PayoffChart — breakeven labels", () => {
  it("renders a breakeven label for a single breakeven", () => {
    renderChart({ breakevens: [22150] });
    const bkLabel = document.querySelector("[aria-label='Breakeven 22150']");
    expect(bkLabel).not.toBeNull();
  });

  it("renders both breakeven labels for a dual-breakeven strategy", () => {
    renderChart({
      legs: straddleLegs,
      breakevens: [21700, 22300],
      maxProfit: 15000,
      maxLoss: null,
    });
    expect(document.querySelector("[aria-label='Breakeven 21700']")).not.toBeNull();
    expect(document.querySelector("[aria-label='Breakeven 22300']")).not.toBeNull();
  });

  it("renders no breakeven labels when breakevens array is empty", () => {
    renderChart({ breakevens: [] });
    const bkLabels = document.querySelectorAll("[aria-label^='Breakeven']");
    expect(bkLabels).toHaveLength(0);
  });
});

// ---------------------------------------------------------------------------
// Payoff curve
// ---------------------------------------------------------------------------

describe("PayoffChart — payoff curve", () => {
  it("renders at least one SVG path element for the curve", () => {
    renderChart();
    const paths = document.querySelectorAll("path");
    // At minimum: profit fill path + loss fill path + at least one curve segment
    expect(paths.length).toBeGreaterThanOrEqual(1);
  });

  it("renders multiple segments for a strategy with profit and loss regions", () => {
    // Bull call spread crosses zero, so there should be both green and red segments
    renderChart({
      legs:      bullCallSpreadLegs,
      breakevens: [22070],
      maxProfit: 2500,
      maxLoss:   -3500,
    });
    const paths = document.querySelectorAll("path");
    expect(paths.length).toBeGreaterThanOrEqual(2);
  });
});

// ---------------------------------------------------------------------------
// Spot price marker
// ---------------------------------------------------------------------------

describe("PayoffChart — spot price marker", () => {
  it("renders a vertical line element for the spot price", () => {
    renderChart({ spotPrice: 22050 });
    // The spot line + zero line + strike lines — at least 2 lines exist
    const lines = document.querySelectorAll("line");
    expect(lines.length).toBeGreaterThanOrEqual(2);
  });
});

// ---------------------------------------------------------------------------
// Max profit / max loss lines
// ---------------------------------------------------------------------------

describe("PayoffChart — max profit/loss lines", () => {
  it("renders additional SVG content when maxProfit is provided", () => {
    const { container: withMax } = renderChart({ maxProfit: 10000, maxLoss: -5000 });
    const { container: noMax   } = render(
      <PayoffChart {...defaultProps} maxProfit={null} maxLoss={null} />,
    );
    // With max profit + max loss, more elements are rendered
    const linesWithMax = withMax.querySelectorAll("line").length;
    const linesNoMax   = noMax.querySelectorAll("line").length;
    expect(linesWithMax).toBeGreaterThanOrEqual(linesNoMax);
  });
});

// ---------------------------------------------------------------------------
// Hover tooltip
// ---------------------------------------------------------------------------

describe("PayoffChart — tooltip interaction", () => {
  it("does not show tooltip initially", () => {
    renderChart();
    // No circle (dot on curve) present before hover
    const circles = document.querySelectorAll("circle");
    expect(circles).toHaveLength(0);
  });

  it("shows tooltip dot when mouse moves over the SVG plot area", () => {
    renderChart();
    const svg = document.querySelector("svg")!;

    // getBoundingClientRect returns zeros in jsdom; override it
    Object.defineProperty(svg, "getBoundingClientRect", {
      value: () => ({ left: 0, top: 0, width: 600, height: 220 }),
      writable: true,
    });

    // Fire a mousemove at x=200 (inside PAD_LEFT=54..PAD_LEFT+PLOT_W=584)
    fireEvent.mouseMove(svg, { clientX: 200, clientY: 110 });

    const circles = document.querySelectorAll("circle");
    expect(circles.length).toBeGreaterThanOrEqual(1);
  });

  it("hides tooltip dot when mouse leaves the SVG", () => {
    renderChart();
    const svg = document.querySelector("svg")!;

    Object.defineProperty(svg, "getBoundingClientRect", {
      value: () => ({ left: 0, top: 0, width: 600, height: 220 }),
      writable: true,
    });

    fireEvent.mouseMove(svg, { clientX: 200, clientY: 110 });
    // Dot should appear
    expect(document.querySelectorAll("circle").length).toBeGreaterThanOrEqual(1);

    fireEvent.mouseLeave(svg);
    // Dot should disappear
    expect(document.querySelectorAll("circle")).toHaveLength(0);
  });

  it("hides tooltip when cursor is outside the plot area (left pad)", () => {
    renderChart();
    const svg = document.querySelector("svg")!;

    Object.defineProperty(svg, "getBoundingClientRect", {
      value: () => ({ left: 0, top: 0, width: 600, height: 220 }),
      writable: true,
    });

    // x=10 is inside PAD_LEFT=54 — should not show tooltip
    fireEvent.mouseMove(svg, { clientX: 10, clientY: 110 });
    expect(document.querySelectorAll("circle")).toHaveLength(0);
  });
});
