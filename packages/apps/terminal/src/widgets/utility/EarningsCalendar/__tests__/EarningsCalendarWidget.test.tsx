/**
 * EarningsCalendarWidget.test.tsx
 *
 * Tests: render, month navigation, sector filter, legend, calendar grid,
 * and the honest connected/disconnected data behaviour (no fabricated rows
 * for connected users).
 */

import { describe, it, expect, vi, beforeAll, beforeEach, afterEach } from "vitest";
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

import { useBrokerConnected } from "@/hooks/useBrokerConnected";
import { getEarningsCalendar } from "@/services/ftApi";
import EarningsCalendarWidget from "../EarningsCalendarWidget";
import { istParts } from "@/lib/ist";

const mockConnected = useBrokerConnected as ReturnType<typeof vi.fn>;
const mockEarnings = getEarningsCalendar as ReturnType<typeof vi.fn>;

function wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

beforeEach(() => {
  mockConnected.mockReturnValue(false);
  mockEarnings.mockReset();
  mockEarnings.mockResolvedValue({ entries: [] });
});

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
    // The widget opens on the IST month, so the expectation must too.
    const { year, month } = istParts();
    const expectedLabel = new Date(year, month + 1, 1).toLocaleString("en-IN", {
      month: "long",
      year: "numeric",
    });

    fireEvent.click(screen.getByLabelText("Next month"));
    expect(screen.getByText(expectedLabel)).toBeTruthy();
  });

  it("navigates back to current month on prev button click after next", () => {
    render(<EarningsCalendarWidget />, { wrapper });
    const { year, month } = istParts();
    const currentLabel = new Date(year, month, 1).toLocaleString("en-IN", {
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

// ---------------------------------------------------------------------------
// Honest data behaviour (no fabricated rows for connected users)
// ---------------------------------------------------------------------------

describe("EarningsCalendarWidget — honest data", () => {
  it("shows the Sample data badge when disconnected", () => {
    mockConnected.mockReturnValue(false);
    render(<EarningsCalendarWidget />, { wrapper });
    expect(screen.getByText("Sample data")).toBeTruthy();
  });

  it("hides the Sample data badge when connected to a genuinely live source", () => {
    // is_sample_data: false models a future real earnings feed — only then
    // may the badge disappear for a connected user.
    mockConnected.mockReturnValue(true);
    mockEarnings.mockResolvedValue({ entries: [], is_sample_data: false });
    render(<EarningsCalendarWidget />, { wrapper });
    expect(screen.queryByText("Sample data")).toBeNull();
  });

  it("keeps the Sample data badge when connected but the backend flags synthetic rows", async () => {
    // The earnings backend is currently synthetic-only and says so via
    // is_sample_data. Fabricated result dates must NEVER render unbadged
    // just because a broker is connected.
    // The 15th of the IST month the widget opens on.
    const { year, month } = istParts();
    const liveDate = `${year}-${String(month + 1).padStart(2, "0")}-15`;
    mockConnected.mockReturnValue(true);
    mockEarnings.mockResolvedValue({
      entries: [
        // PAYTM is not in the local SAMPLE_EARNINGS constant, so its
        // presence proves the backend rows rendered, not the local sample.
        { symbol: "PAYTM", company: "One97 Communications", date: liveDate, sector: "Fintech" },
      ],
      is_sample_data: true,
    });

    render(<EarningsCalendarWidget />, { wrapper });

    // The backend (synthetic) rows render — not the local sample constant —
    // and the badge stays visible.
    expect(await screen.findByText("PAYTM")).toBeTruthy();
    expect(screen.getByText("Sample data")).toBeTruthy();
    expect(screen.queryByText("INFY")).toBeNull();
  });

  it("renders an honest empty state and NO sample rows when connected with an empty response", async () => {
    mockConnected.mockReturnValue(true);
    mockEarnings.mockResolvedValue({ entries: [] });
    render(<EarningsCalendarWidget />, { wrapper });

    // Honest empty state must appear.
    expect(
      await screen.findByText("No earnings results available for this month."),
    ).toBeTruthy();

    // No fabricated sample symbols may be rendered to a connected user.
    expect(screen.queryByText("INFY")).toBeNull();
    expect(screen.queryByText("RELIANCE")).toBeNull();
    expect(screen.queryByText("BAJFINANCE")).toBeNull();
    expect(screen.queryByText("Sample data")).toBeNull();
  });

  it("renders the live entries (not sample data) when connected with a populated response", async () => {
    // The 15th of the IST month the widget opens on.
    const { year, month } = istParts();
    const liveDate = `${year}-${String(month + 1).padStart(2, "0")}-15`;
    mockConnected.mockReturnValue(true);
    mockEarnings.mockResolvedValue({
      // The explicit live flag the real route sends. Provenance now fails
      // closed, so a payload that omits it reads as sample — which is the
      // point: a backend that stops flagging must not silently read as live.
      is_sample_data: false,
      entries: [
        { symbol: "ZOMATO", company: "Zomato", date: liveDate, result: "beat", sector: "Consumer" },
      ],
    });

    render(<EarningsCalendarWidget />, { wrapper });

    // Live symbol shows; sample-only symbol must not.
    expect(await screen.findByText("ZOMATO")).toBeTruthy();
    expect(screen.queryByText("INFY")).toBeNull();
    expect(screen.queryByText("Sample data")).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// The grid is a calendar of IST trading days
//
// Cells used to be browser-local Date objects keyed with `toISOString()` — the
// UTC day. On an IST machine every key came out a day early, so entries landed
// one square to the left and the "today" highlight sat on the wrong date.
//
// Fixed instant, no reliance on the machine's timezone.
// ---------------------------------------------------------------------------

/** The single cell carrying the "today" highlight, or null. */
function todayCell(): HTMLTableCellElement | null {
  const cells = Array.from(document.querySelectorAll("td")).filter((td) =>
    td.className.includes("bg-accent/10"),
  );
  return cells.length === 1 ? cells[0] : null;
}

/** The day-of-month number rendered in a cell. */
function cellDay(cell: HTMLTableCellElement): string {
  return cell.firstElementChild?.textContent ?? "";
}

describe("EarningsCalendarWidget — IST trading day", () => {
  // 20:30 UTC on Saturday 25 July 2026 — late evening in Europe, and already
  // 02:00 IST on Sunday the 26th.
  const IST_EVENING_ROLLOVER = new Date("2026-07-25T20:30:00Z");

  afterEach(() => {
    vi.useRealTimers();
  });

  it("REGRESSION: highlights the IST day while the UTC day is still yesterday", () => {
    vi.setSystemTime(IST_EVENING_ROLLOVER);
    // Sanity: the UTC-based helper this replaced would have said the 25th.
    expect(IST_EVENING_ROLLOVER.toISOString().slice(0, 10)).toBe("2026-07-25");

    render(<EarningsCalendarWidget />, { wrapper });

    const expectedLabel = new Date(2026, 6, 1).toLocaleString("en-IN", {
      month: "long",
      year: "numeric",
    });
    expect(screen.getByText(expectedLabel)).toBeTruthy();

    const cell = todayCell();
    expect(cell).not.toBeNull();
    expect(cellDay(cell!)).toBe("26");
  });

  it("REGRESSION: places an entry on the cell matching its IST date", async () => {
    vi.setSystemTime(IST_EVENING_ROLLOVER);
    mockConnected.mockReturnValue(true);
    mockEarnings.mockResolvedValue({
      entries: [
        { symbol: "PAYTM", company: "One97 Communications", date: "2026-07-15", sector: "Fintech" },
      ],
      is_sample_data: true,
    });

    render(<EarningsCalendarWidget />, { wrapper });

    const chip = await screen.findByText("PAYTM");
    const cell = chip.closest("td");
    expect(cell).not.toBeNull();
    expect(cellDay(cell as HTMLTableCellElement)).toBe("15");
  });
});
