/**
 * EconomicCalendarWidget.test.tsx
 *
 * Tests: render, filter, impact legend, event display, date grouping, and the
 * backend wiring (backend events render; bundled sample is the offline
 * fallback; the honest sample badge stays either way).
 */

import { describe, it, expect, vi, beforeAll, beforeEach, afterEach } from "vitest";
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
import { toIstIsoDate } from "@/lib/ist";

function renderWidget() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <EconomicCalendarWidget />
    </QueryClientProvider>,
  );
}

function isoDaysAhead(offset: number): string {
  return toIstIsoDate(new Date(Date.now() + offset * 86_400_000));
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

// ---------------------------------------------------------------------------
// "Today" is the IST trading day
//
// Event dates arrive as IST calendar days. The widget used to compare them
// against `new Date().toISOString().slice(0, 10)` — the UTC day — so for the
// whole 00:00–05:30 IST window today's events lost their "Today" heading and
// were greyed out as past.
//
// Fixed instant, no reliance on the machine's timezone.
// ---------------------------------------------------------------------------

describe("EconomicCalendarWidget — IST trading day", () => {
  // 20:30 UTC on Saturday 25 July 2026 — late evening in Europe, and already
  // 02:00 IST on Sunday the 26th.
  const IST_EVENING_ROLLOVER = new Date("2026-07-25T20:30:00Z");

  afterEach(() => {
    vi.useRealTimers();
  });

  it("REGRESSION: heads the IST day 'Today' while the UTC day is still yesterday", async () => {
    vi.setSystemTime(IST_EVENING_ROLLOVER);
    // Sanity: the UTC-based helper this replaced would have said the 25th.
    expect(IST_EVENING_ROLLOVER.toISOString().slice(0, 10)).toBe("2026-07-25");

    mockCalendar.mockResolvedValue({
      days: 30,
      events: [
        {
          date: "2026-07-26", time: "10:00", event: "IST Day CPI",
          country: "IN", impact: "high", previous: null, forecast: null,
          actual: null, category: "cpi",
        },
      ],
    });

    renderWidget();

    expect(await screen.findByText("IST Day CPI")).toBeInTheDocument();
    expect(screen.getByText("Today")).toBeInTheDocument();
  });

  it("still marks the previous IST day as past, not today", async () => {
    vi.setSystemTime(IST_EVENING_ROLLOVER);
    mockCalendar.mockResolvedValue({
      days: 30,
      events: [
        {
          date: "2026-07-25", time: "10:00", event: "Yesterday CPI",
          country: "IN", impact: "high", previous: null, forecast: null,
          actual: null, category: "cpi",
        },
      ],
    });

    renderWidget();

    expect(await screen.findByText("Yesterday CPI")).toBeInTheDocument();
    expect(screen.queryByText("Today")).not.toBeInTheDocument();
  });
});
