/**
 * EconomicCalendarWidget.test.tsx
 *
 * Tests: render, filter, impact legend, event display, date grouping, and the
 * backend wiring (backend events render; bundled sample is the offline
 * fallback; the honest sample badge stays either way).
 */

import { describe, it, expect, vi, beforeAll, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

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

const mockCalendar = vi.fn();
vi.mock("@/services/ftApi", () => ({
  getEconomicCalendar: (...a: unknown[]) => mockCalendar(...a),
}));

import EconomicCalendarWidget from "../EconomicCalendarWidget";

function renderWidget() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <EconomicCalendarWidget />
    </QueryClientProvider>,
  );
}

function isoDaysAhead(offset: number): string {
  const d = new Date();
  d.setDate(d.getDate() + offset);
  return d.toISOString().slice(0, 10);
}

beforeEach(() => {
  mockCalendar.mockReset();
  // default: backend unavailable → widget falls back to the bundled sample
  mockCalendar.mockRejectedValue(new Error("backend offline"));
});

describe("EconomicCalendarWidget", () => {
  it("renders the widget header", () => {
    renderWidget();
    expect(screen.getByText("Economic Calendar")).toBeTruthy();
  });

  it("shows the permanent 'Sample data' badge", () => {
    renderWidget();
    const badge = screen.getByText("Sample data");
    expect(badge).toBeTruthy();
    expect(badge.getAttribute("role")).toBe("status");
  });

  it("renders the impact legend with all three levels", () => {
    renderWidget();
    expect(screen.getByText("high")).toBeTruthy();
    expect(screen.getByText("medium")).toBeTruthy();
    expect(screen.getByText("low")).toBeTruthy();
  });

  it("renders country filter select", () => {
    renderWidget();
    expect(screen.getByLabelText("Filter by country")).toBeTruthy();
  });

  it("renders impact filter select", () => {
    renderWidget();
    expect(screen.getByLabelText("Filter by impact")).toBeTruthy();
  });

  it("shows at least one RBI-related event (bundled fallback)", () => {
    renderWidget();
    const rbiEvents = screen.getAllByText(/RBI/i);
    expect(rbiEvents.length).toBeGreaterThanOrEqual(1);
  });

  it("shows events count label", () => {
    renderWidget();
    expect(screen.getByText(/\d+ events/)).toBeTruthy();
  });

  it("renders the timeline region", () => {
    renderWidget();
    expect(screen.getByRole("list", { name: "Economic events timeline" })).toBeTruthy();
  });

  it("renders BACKEND events when the calendar route responds", async () => {
    mockCalendar.mockResolvedValue({
      days: 30,
      events: [
        {
          date: isoDaysAhead(2),
          time: "14:00",
          event: "Backend CPI YoY",
          country: "IN",
          impact: "high",
          previous: "5.1%",
          forecast: "5.0%",
          actual: null,
          category: "cpi",
        },
        {
          date: isoDaysAhead(3),
          time: "19:30",
          event: "Backend Fed Rate Decision",
          country: "US",
          impact: "high",
          previous: "5.50%",
          forecast: "5.50%",
          actual: null,
          category: "interest_rate",
        },
      ],
    });

    renderWidget();

    expect(await screen.findByText("Backend CPI YoY")).toBeInTheDocument();
    expect(screen.getByText("Backend Fed Rate Decision")).toBeInTheDocument();
    await waitFor(() => expect(mockCalendar).toHaveBeenCalledWith(30));
    // the badge stays — the backend provider is itself sample-only today
    expect(screen.getByText("Sample data")).toBeInTheDocument();
  });

  it("skips backend events from countries the widget cannot render", async () => {
    mockCalendar.mockResolvedValue({
      days: 30,
      events: [
        {
          date: isoDaysAhead(1), time: "10:00", event: "Unknown-land PMI",
          country: "ZZ", impact: "low", previous: null, forecast: null,
          actual: null, category: "pmi",
        },
      ],
    });

    renderWidget();

    // the lone unmappable event is filtered → falls back to the bundled sample
    await waitFor(() => expect(mockCalendar).toHaveBeenCalled());
    expect(screen.queryByText("Unknown-land PMI")).not.toBeInTheDocument();
    expect(screen.getAllByText(/RBI/i).length).toBeGreaterThanOrEqual(1);
  });
});
