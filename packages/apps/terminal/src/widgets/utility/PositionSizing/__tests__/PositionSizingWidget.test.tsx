import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import "@testing-library/jest-dom";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

vi.mock("@/hooks/useTrackBehavior", () => ({
  useTrackBehavior: () => vi.fn(),
}));

import PositionSizingWidget from "../PositionSizingWidget";

/** Read the value cell of a labelled result/legend row. */
function resultValue(label: string): string {
  const row = screen.getByText(label).closest("div");
  return row?.querySelector("span:last-child")?.textContent?.trim() ?? "";
}

describe("PositionSizingWidget", () => {
  it("renders widget header with title", () => {
    render(<PositionSizingWidget />);
    expect(screen.getByText("Position Sizing")).toBeTruthy();
  });

  it("renders three method tabs", () => {
    render(<PositionSizingWidget />);
    expect(screen.getByRole("tab", { name: "Fixed %" })).toBeTruthy();
    expect(screen.getByRole("tab", { name: "Kelly" })).toBeTruthy();
    expect(screen.getByRole("tab", { name: "ATR" })).toBeTruthy();
  });

  it("Fixed % tab is active by default", () => {
    render(<PositionSizingWidget />);
    const tab = screen.getByRole("tab", { name: "Fixed %" });
    expect(tab.getAttribute("aria-selected")).toBe("true");
  });

  it("shows results with default Fixed % values", () => {
    render(<PositionSizingWidget />);
    expect(screen.getByText("Position Size (lots)")).toBeTruthy();
    expect(screen.getByText("Rupee Risk")).toBeTruthy();
    expect(screen.getByText("Max Loss")).toBeTruthy();
  });

  it("renders capital allocation through the shared Flint donut primitive", () => {
    render(<PositionSizingWidget />);
    const chart = screen.getByRole("img", { name: /capital allocation/i });
    expect(chart).toHaveClass("rounded-full");
    expect(chart.getAttribute("style")).toContain("conic-gradient");
    expect(chart.querySelector("svg")).not.toBeInTheDocument();
  });

  it("switches to Kelly tab and shows Kelly inputs", () => {
    render(<PositionSizingWidget />);
    fireEvent.click(screen.getByRole("tab", { name: "Kelly" }));
    expect(screen.getByLabelText("Win Rate %")).toBeTruthy();
    expect(screen.getByLabelText("Reward : Risk")).toBeTruthy();
  });

  it("switches to ATR tab and shows ATR inputs", () => {
    render(<PositionSizingWidget />);
    fireEvent.click(screen.getByRole("tab", { name: "ATR" }));
    expect(screen.getByLabelText("ATR Value")).toBeTruthy();
    expect(screen.getByLabelText("ATR Multiplier")).toBeTruthy();
  });

  it("shows empty state when account capital is cleared", () => {
    render(<PositionSizingWidget />);
    const capitalInput = screen.getByLabelText("Account Capital");
    fireEvent.change(capitalInput, { target: { value: "" } });
    expect(screen.getByText(/fill in all fields/i)).toBeTruthy();
  });

  it("has correct aria label on widget container", () => {
    render(<PositionSizingWidget />);
    expect(screen.getByLabelText("Position Sizing widget")).toBeTruthy();
  });

  it("renders At Risk and Available pie legend labels", () => {
    render(<PositionSizingWidget />);
    expect(screen.getByText("At Risk")).toBeTruthy();
    expect(screen.getByText("Available")).toBeTruthy();
  });

  // ── Numeric characterisation (pins the sizing kernel) ──────────────────────
  //
  // These pin the exact arithmetic of each sizing method so that extracting the
  // kernel into `lib/sizing.ts` cannot silently change a number.

  describe("sizing arithmetic", () => {
    it("pins the default Fixed % result — 1 lot, clamped above the risk budget", () => {
      render(<PositionSizingWidget />);

      // Capital ₹5,00,000 · risk 1% → budget ₹5,000.
      // Risk per lot = 200 × 50 = ₹10,000, so floor() lands on 0 and the
      // max(1, …) clamp recommends a lot that risks 2× the stated budget.
      expect(resultValue("Position Size (lots)")).toBe("1");
      expect(resultValue("Units (shares)")).toBe("50");
      expect(resultValue("Rupee Risk")).toBe("₹10,000");
      expect(resultValue("Max Loss")).toBe("₹10,000");
      expect(resultValue("At Risk")).toBe("2.00%");
      expect(resultValue("Available")).toBe("98.00%");

      // …and the clamp is now stated out loud instead of passing silently.
      expect(screen.getByRole("status")).toHaveTextContent(
        /single lot risks ₹10,000 — more than the ₹5,000 you allowed/i,
      );
    });

    it("pins Fixed % sizing when the budget covers several lots", () => {
      render(<PositionSizingWidget />);
      fireEvent.change(screen.getByLabelText("Stop Loss Distance"), {
        target: { value: "50" },
      });

      // Budget ₹5,000 / (50 × 50 = ₹2,500 per lot) → 2 lots exactly.
      expect(resultValue("Position Size (lots)")).toBe("2");
      expect(resultValue("Units (shares)")).toBe("100");
      expect(resultValue("Rupee Risk")).toBe("₹5,000");
      expect(resultValue("At Risk")).toBe("1.00%");
      // Within budget → no warning.
      expect(screen.queryByRole("status")).not.toBeInTheDocument();
    });

    it("pins the default half-Kelly result", () => {
      render(<PositionSizingWidget />);
      fireEvent.click(screen.getByRole("tab", { name: "Kelly" }));

      // 55% win rate at 2R → full Kelly (0.55 × 2 − 0.45) / 2 = 32.5%,
      // half-Kelly 16.25% → budget ₹81,250 / ₹10,000 per lot → 8 lots.
      expect(resultValue("Position Size (lots)")).toBe("8");
      expect(resultValue("Units (shares)")).toBe("400");
      expect(resultValue("Rupee Risk")).toBe("₹80,000");
      expect(resultValue("At Risk")).toBe("16.00%");
      // Half-Kelly sized the budget itself, so nothing is over-risked.
      expect(screen.queryByRole("status")).not.toBeInTheDocument();
    });

    it("pins the default ATR result — also clamped above the risk budget", () => {
      render(<PositionSizingWidget />);
      fireEvent.click(screen.getByRole("tab", { name: "ATR" }));

      // Stop distance = ATR 180 × 1.5 = 270 → ₹13,500 per lot vs a ₹5,000
      // budget, so the clamp again recommends 1 over-risked lot.
      expect(resultValue("Position Size (lots)")).toBe("1");
      expect(resultValue("Units (shares)")).toBe("50");
      expect(resultValue("Rupee Risk")).toBe("₹13,500");
      expect(resultValue("At Risk")).toBe("2.70%");
      expect(screen.getByRole("status")).toHaveTextContent(
        /single lot risks ₹13,500 — more than the ₹5,000 you allowed/i,
      );
    });
  });
});
