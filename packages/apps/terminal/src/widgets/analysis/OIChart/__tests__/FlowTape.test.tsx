/**
 * FlowTape.test.tsx — the large-trade tape folded in from Options Flow (D1).
 */

import { describe, it, expect } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import "@testing-library/jest-dom";
import { FlowTapeSection, SAMPLE_FLOW_TAPE } from "../FlowTape";

describe("FlowTapeSection", () => {
  it("starts collapsed and always carries the illustrative-sample label", () => {
    render(<FlowTapeSection />);
    // The disclosure is on the toggle itself, so it is visible even collapsed.
    expect(
      screen.getByText(/illustrative sample — no large-trade feed exists yet/i),
    ).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("expands to the sample rows with their activity badges", () => {
    render(<FlowTapeSection />);
    fireEvent.click(screen.getByRole("button", { name: /large-trade tape/i }));

    expect(screen.getByRole("table")).toBeInTheDocument();
    expect(screen.getAllByText(/sweep|block|oi spike/i).length).toBeGreaterThan(0);
    // Every sample row renders.
    expect(document.querySelectorAll("tbody tr")).toHaveLength(SAMPLE_FLOW_TAPE.length);
  });

  it("toggles premium sort and reorders the rows", () => {
    render(<FlowTapeSection />);
    fireEvent.click(screen.getByRole("button", { name: /large-trade tape/i }));
    fireEvent.click(screen.getByRole("button", { name: /sorted by time/i }));

    const firstRow = document.querySelector("tbody tr");
    // Highest premium in the sample set is f3 (₹1.13 crore).
    expect(firstRow?.textContent).toContain("24400");
  });
});
