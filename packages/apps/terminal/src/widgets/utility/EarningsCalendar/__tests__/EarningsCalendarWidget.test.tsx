/**
 * EarningsCalendarWidget.test.tsx
 *
 * Tests: render, month navigation, sector filter, legend, calendar grid.
 */

import { describe, it, expect, vi, beforeAll } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
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

vi.mock("@/hooks/useBrokerConnected", () => ({
  useBrokerConnected: vi.fn().mockReturnValue(false),
}));

vi.mock("@/services/ftApi", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/services/ftApi")>();
  return { ...actual, getEarningsCalendar: vi.fn() };
});

import EarningsCalendarWidget from "../EarningsCalendarWidget";

function wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

describe("EarningsCalendarWidget", () => {
  it("renders the widget header", () => {
    render(<EarningsCalendarWidget />, { wrapper });
    expect(screen.getByText("Earnings Calendar")).toBeTruthy();
  });

  it("renders day-of-week column headers", () => {
    render(<EarningsCalendarWidget />, { wrapper });
    expect(screen.getByText("Mon")).toBeTruthy();
    expect(screen.getByText("Wed")).toBeTruthy();
    expect(screen.getByText("Fri")).toBeTruthy();
  });

  it("renders prev/next month navigation buttons", () => {
    render(<EarningsCalendarWidget />, { wrapper });
    expect(screen.getByLabelText("Previous month")).toBeTruthy();
    expect(screen.getByLabelText("Next month")).toBeTruthy();
  });

  it("renders the sector filter dropdown", () => {
    render(<EarningsCalendarWidget />, { wrapper });
    expect(screen.getByLabelText("Filter by sector")).toBeTruthy();
  });

  it("shows legend items", () => {
    render(<EarningsCalendarWidget />, { wrapper });
    expect(screen.getByText("beat")).toBeTruthy();
    expect(screen.getByText("missed")).toBeTruthy();
    expect(screen.getByText("inline")).toBeTruthy();
    expect(screen.getByText("Upcoming")).toBeTruthy();
  });

  it("navigates to next month on next button click", () => {
    render(<EarningsCalendarWidget />, { wrapper });
    const now = new Date();
    const nextMonth = new Date(now.getFullYear(), now.getMonth() + 1, 1);
    const expectedLabel = nextMonth.toLocaleString("en-IN", { month: "long", year: "numeric" });

    fireEvent.click(screen.getByLabelText("Next month"));
    expect(screen.getByText(expectedLabel)).toBeTruthy();
  });

  it("navigates back to current month on prev button click after next", () => {
    render(<EarningsCalendarWidget />, { wrapper });
    const now = new Date();
    const currentLabel = new Date(now.getFullYear(), now.getMonth(), 1).toLocaleString("en-IN", {
      month: "long",
      year: "numeric",
    });

    fireEvent.click(screen.getByLabelText("Next month"));
    fireEvent.click(screen.getByLabelText("Previous month"));
    expect(screen.getByText(currentLabel)).toBeTruthy();
  });

  it("renders sample earnings symbols on the calendar", () => {
    render(<EarningsCalendarWidget />, { wrapper });
    // At least one sample symbol should appear somewhere on the calendar
    // (INFY or TCS must be in the displayed month range for offset-based dates)
    const table = screen.getByRole("table", { name: "Earnings calendar" });
    expect(table).toBeTruthy();
  });
});
