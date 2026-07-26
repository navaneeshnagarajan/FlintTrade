/**
 * DeliveryDataWidget.test — ported from the Market Intelligence Delivery Data
 * tab's coverage (ruling D4), plus the provenance tests the tab never had.
 *
 * The tab lived inside a tool whose header decided provenance for it; as a
 * standalone widget the badge is its own responsibility, and because no live
 * delivery route exists it must be unconditional.
 */

import { describe, it, expect } from "vitest";
import { render, screen, fireEvent, within } from "@testing-library/react";
import "@testing-library/jest-dom";

import DeliveryDataWidget, {
  SAMPLE_DELIVERY_ROWS,
  deliveryBand,
} from "../DeliveryDataWidget";

function rowSymbols(): string[] {
  const table = screen.getByRole("table");
  return within(table)
    .getAllByRole("row")
    .slice(1) // drop the header row
    .map((row) => within(row).getAllByRole("cell")[0].textContent ?? "")
    .map((text) => text.replace(/[+-][\d.]+%$/, ""));
}

describe("DeliveryDataWidget", () => {
  it("renders every sample row", () => {
    render(<DeliveryDataWidget />);
    for (const row of SAMPLE_DELIVERY_ROWS) {
      expect(screen.getByText(row.symbol)).toBeInTheDocument();
    }
  });

  it("carries an unconditional sample badge — there is no live delivery route", () => {
    render(<DeliveryDataWidget />);
    const badge = screen.getByRole("status", { name: /sample delivery data/i });
    expect(badge).toHaveTextContent("Sample data");
    expect(badge.getAttribute("title")).toMatch(/no live delivery source is wired/i);
  });

  it("names the missing source rather than implying the data is merely late", () => {
    render(<DeliveryDataWidget />);
    expect(screen.getByText(/no read route serves\s+per-symbol delivery yet/i)).toBeInTheDocument();
  });

  it("sorts by delivery percentage, descending, by default", () => {
    render(<DeliveryDataWidget />);
    const header = screen.getByRole("columnheader", { name: /Delivery %/ });
    expect(header).toHaveAttribute("aria-sort", "descending");
    expect(rowSymbols()[0]).toBe("HDFCBANK"); // 78.4%
    expect(rowSymbols().at(-1)).toBe("AXISBANK"); // 44.2%
  });

  it("reverses the direction when the active column is clicked again", () => {
    render(<DeliveryDataWidget />);
    fireEvent.click(screen.getByRole("button", { name: "Sort by Delivery %" }));

    expect(screen.getByRole("columnheader", { name: /Delivery %/ })).toHaveAttribute(
      "aria-sort",
      "ascending",
    );
    expect(rowSymbols()[0]).toBe("AXISBANK");
    expect(rowSymbols().at(-1)).toBe("HDFCBANK");
  });

  it("sorts alphabetically on a text column", () => {
    render(<DeliveryDataWidget />);
    fireEvent.click(screen.getByRole("button", { name: "Sort by Symbol" }));

    expect(rowSymbols()[0]).toBe("WIPRO");
    fireEvent.click(screen.getByRole("button", { name: "Sort by Symbol" }));
    expect(rowSymbols()[0]).toBe("AXISBANK");
  });

  it("sorts numerically on a price column", () => {
    render(<DeliveryDataWidget />);
    fireEvent.click(screen.getByRole("button", { name: "Sort by Close" }));
    expect(rowSymbols()[0]).toBe("BAJFINANCE"); // 6848.0, the highest close
  });

  it("bands delivery percentage by conviction at the documented thresholds", () => {
    expect(deliveryBand(78.4).label).toBe("High conviction");
    expect(deliveryBand(60).label).toBe("High conviction");
    expect(deliveryBand(59.9).label).toBe("Medium conviction");
    expect(deliveryBand(45).label).toBe("Medium conviction");
    expect(deliveryBand(44.9).label).toBe("Low conviction");
    expect(deliveryBand(0).label).toBe("Low conviction");
  });

  it("renders a delivery meter per row with an accessible name", () => {
    render(<DeliveryDataWidget />);
    const meters = screen.getAllByLabelText(/delivery percentage$/);
    expect(meters).toHaveLength(SAMPLE_DELIVERY_ROWS.length);
    expect(screen.getByLabelText("HDFCBANK delivery percentage")).toBeInTheDocument();
  });

  it("shows the session change derived from open and close", () => {
    render(<DeliveryDataWidget />);
    // TCS: 3840.0 → 3848.5 = +0.22%.
    expect(screen.getByText("+0.22%")).toBeInTheDocument();
  });

  it("renders the conviction legend", () => {
    render(<DeliveryDataWidget />);
    expect(screen.getByText("High ≥60%")).toBeInTheDocument();
    expect(screen.getByText("Medium 45–60%")).toBeInTheDocument();
    expect(screen.getByText(/Low <45%/)).toBeInTheDocument();
  });
});
