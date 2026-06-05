/**
 * EconomicCalendarWidget.test.tsx
 *
 * Tests: render, filter, impact legend, event display, date grouping.
 */

import { describe, it, expect, vi, beforeAll } from "vitest";
import { render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";

beforeAll(() => {
  global.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
});

vi.mock("@/hooks/useTrackBehavior", () => ({
  useTrackBehavior: () => vi.fn(),
}));

import EconomicCalendarWidget from "../EconomicCalendarWidget";

describe("EconomicCalendarWidget", () => {
  it("renders the widget header", () => {
    render(<EconomicCalendarWidget />);
    expect(screen.getByText("Economic Calendar")).toBeTruthy();
  });

  it("shows the permanent 'Sample data' badge", () => {
    render(<EconomicCalendarWidget />);
    const badge = screen.getByText("Sample data");
    expect(badge).toBeTruthy();
    expect(badge.getAttribute("role")).toBe("status");
  });

  it("renders the impact legend with all three levels", () => {
    render(<EconomicCalendarWidget />);
    expect(screen.getByText("high")).toBeTruthy();
    expect(screen.getByText("medium")).toBeTruthy();
    expect(screen.getByText("low")).toBeTruthy();
  });

  it("renders country filter select", () => {
    render(<EconomicCalendarWidget />);
    expect(screen.getByLabelText("Filter by country")).toBeTruthy();
  });

  it("renders impact filter select", () => {
    render(<EconomicCalendarWidget />);
    expect(screen.getByLabelText("Filter by impact")).toBeTruthy();
  });

  it("shows at least one RBI-related event", () => {
    render(<EconomicCalendarWidget />);
    const rbiEvents = screen.getAllByText(/RBI/i);
    expect(rbiEvents.length).toBeGreaterThanOrEqual(1);
  });

  it("shows events count label", () => {
    render(<EconomicCalendarWidget />);
    expect(screen.getByText(/\d+ events/)).toBeTruthy();
  });

  it("renders the timeline region", () => {
    render(<EconomicCalendarWidget />);
    expect(screen.getByRole("list", { name: "Economic events timeline" })).toBeTruthy();
  });
});
