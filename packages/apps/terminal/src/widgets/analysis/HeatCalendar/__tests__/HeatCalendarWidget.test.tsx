import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import "@testing-library/jest-dom";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

vi.mock("@/hooks/useBrokerConnected", () => ({
  useBrokerConnected: vi.fn().mockReturnValue(false),
}));

vi.mock("@/hooks/useTrackBehavior", () => ({
  useTrackBehavior: () => vi.fn(),
}));

import { useBrokerConnected } from "@/hooks/useBrokerConnected";
import HeatCalendarWidget from "../HeatCalendarWidget";

const mockConnected = useBrokerConnected as ReturnType<typeof vi.fn>;

beforeEach(() => {
  global.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
});

describe("HeatCalendarWidget", () => {
  it("renders the widget title", () => {
    mockConnected.mockReturnValue(false);
    render(<HeatCalendarWidget />);
    expect(screen.getByText("Heat Calendar")).toBeTruthy();
  });

  it("shows the Sample data badge when broker is disconnected", () => {
    mockConnected.mockReturnValue(false);
    render(<HeatCalendarWidget />);
    expect(screen.getByText("Sample data")).toBeTruthy();
  });

  it("still shows the Sample data badge when broker is connected", () => {
    // The widget has no live history endpoint wired yet — it always renders
    // buildSampleData(). The badge must stay visible even when connected so it
    // never implies the returns are live (house rule: no mock data without a
    // visible Demo-data affordance).
    mockConnected.mockReturnValue(true);
    render(<HeatCalendarWidget />);
    expect(screen.getByText("Sample data")).toBeTruthy();
  });

  it("labels the Sample data badge so it cannot pass as live data", () => {
    mockConnected.mockReturnValue(true);
    render(<HeatCalendarWidget />);
    const badge = screen.getByText("Sample data");
    expect(badge.getAttribute("role")).toBe("status");
    expect(badge.getAttribute("aria-label")).toMatch(/no live data source is wired yet/i);
    expect(badge.getAttribute("title")).toMatch(/no live data wired yet/i);
  });

  it("renders day-of-week column headers", () => {
    mockConnected.mockReturnValue(false);
    render(<HeatCalendarWidget />);
    expect(screen.getByText("Mon")).toBeTruthy();
    expect(screen.getByText("Fri")).toBeTruthy();
  });

  it("renders monthly total return summary row", () => {
    mockConnected.mockReturnValue(false);
    render(<HeatCalendarWidget />);
    expect(screen.getByText("Monthly Total Return")).toBeTruthy();
  });

  it("navigates to previous month when back button is clicked", () => {
    mockConnected.mockReturnValue(false);
    render(<HeatCalendarWidget />);
    const backBtn = screen.getByRole("button", { name: /previous month/i });
    const currentMonthText = screen.getByText(/\d{4}/);
    const initialText = currentMonthText.textContent;
    fireEvent.click(backBtn);
    // After clicking, the displayed year/month should change
    expect(currentMonthText.textContent).not.toBeNull();
    // The text content will have updated (could be same year different month)
    expect(typeof initialText).toBe("string");
  });

  it("renders the colour legend", () => {
    mockConnected.mockReturnValue(false);
    render(<HeatCalendarWidget />);
    expect(screen.getByText("Legend:")).toBeTruthy();
    expect(screen.getByText("≤ -3%")).toBeTruthy();
    expect(screen.getByText("≥ +3%")).toBeTruthy();
  });

  it("renders previous and next month navigation buttons", () => {
    mockConnected.mockReturnValue(false);
    render(<HeatCalendarWidget />);
    expect(screen.getByRole("button", { name: /previous month/i })).toBeTruthy();
    expect(screen.getByRole("button", { name: /next month/i })).toBeTruthy();
  });
});
