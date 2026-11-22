import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, act, fireEvent } from "@testing-library/react";
import "@testing-library/jest-dom";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

vi.mock("@/hooks/useTrackBehavior", () => ({
  useTrackBehavior: () => vi.fn(),
}));

const apiMocks = vi.hoisted(() => ({ getExpiry: vi.fn() }));
vi.mock("@/services/api", () => ({ getExpiry: apiMocks.getExpiry }));

import ExpiryCountdownWidget, { computeExpiries, formatExpiryDate } from "../ExpiryCountdownWidget";
import { istParts, toIstIsoDate } from "@/lib/ist";

// Contract lists used below (all dates IST).
//
// NIFTY contracts expire on Tuesdays and SENSEX contracts on Thursdays. The
// widget must read both off the list rather than assume either weekday.
//   NIFTY : Tue 24 Nov 2026 is the November monthly, Tue 29 Dec 2026 the
//           December (quarterly) one.
//   SENSEX: Thu 26 Nov 2026 is the November monthly, Thu 31 Dec 2026 the
//           December (quarterly) one.

const NIFTY_LIST = [
  "24-NOV-26", "01-DEC-26", "08-DEC-26", "15-DEC-26", "22-DEC-26", "29-DEC-26",
  "26-JAN-27", "30-MAR-27",
];
const SENSEX_LIST = [
  "2026-11-26", "2026-12-03", "2026-12-10", "2026-12-17", "2026-12-24", "2026-12-31",
  "2027-01-28", "2027-03-25",
];

/** Sunday 22 Nov 2026, 09:30 IST. */
const SUNDAY_MORNING = "2026-11-22T04:00:00Z";

function rowsAt(list: readonly string[], iso: string): Record<string, Date | null> {
  return Object.fromEntries(computeExpiries(list, new Date(iso)).map((row) => [row.kind, row.date]));
}

function isoOf(date: Date | null): string | null {
  return date ? toIstIsoDate(date) : null;
}

async function flush() {
  await act(async () => {
    await Promise.resolve();
  });
}

describe("computeExpiries: NIFTY Tuesday expiries", () => {
  it("reads weekly, monthly and quarterly off the list", () => {
    const rows = rowsAt(NIFTY_LIST, SUNDAY_MORNING);
    expect(isoOf(rows.Weekly)).toBe("2026-11-24");
    expect(isoOf(rows.Monthly)).toBe("2026-11-24");
    expect(isoOf(rows.Quarterly)).toBe("2026-12-29");
    for (const date of Object.values(rows)) expect(istParts(date as Date).weekday).toBe(2);
  });

  it("anchors each expiry at the 15:30 IST close", () => {
    expect(istParts(rowsAt(NIFTY_LIST, SUNDAY_MORNING).Weekly as Date)).toMatchObject({ hour: 15, minute: 30 });
  });

  it("keeps today's contract until the close, then rolls to the next listed one", () => {
    // 15:29:59 IST and 16:00 IST on Tue 24 Nov 2026.
    expect(isoOf(rowsAt(NIFTY_LIST, "2026-11-24T09:59:59Z").Weekly)).toBe("2026-11-24");
    const after = rowsAt(NIFTY_LIST, "2026-11-24T10:30:00Z");
    expect(isoOf(after.Weekly)).toBe("2026-12-01");
    expect(isoOf(after.Monthly)).toBe("2026-12-29");
  });

  it("renders the date as it is listed", () => {
    expect(formatExpiryDate(rowsAt(NIFTY_LIST, SUNDAY_MORNING).Weekly as Date)).toBe("Tue 24 Nov");
  });
});

describe("computeExpiries: SENSEX Thursday expiries", () => {
  it("reads weekly, monthly and quarterly off the list", () => {
    const rows = rowsAt(SENSEX_LIST, SUNDAY_MORNING);
    expect(isoOf(rows.Weekly)).toBe("2026-11-26");
    expect(isoOf(rows.Monthly)).toBe("2026-11-26");
    expect(isoOf(rows.Quarterly)).toBe("2026-12-31");
    for (const date of Object.values(rows)) expect(istParts(date as Date).weekday).toBe(4);
    expect(formatExpiryDate(rows.Weekly as Date)).toBe("Thu 26 Nov");
  });
});

describe("computeExpiries: holiday-shifted expiry", () => {
  it("uses the shifted date the list carries, with no weekday rule", () => {
    // The Tuesday 1 Dec contract listed a day early on Monday 30 Nov.
    const shifted = ["30-NOV-26", "08-DEC-26", "15-DEC-26", "22-DEC-26", "28-DEC-26", "26-JAN-27"];
    const rows = rowsAt(shifted, "2026-11-25T04:00:00Z");
    expect(isoOf(rows.Weekly)).toBe("2026-11-30");
    expect(formatExpiryDate(rows.Weekly as Date)).toBe("Mon 30 Nov");
    expect(isoOf(rows.Monthly)).toBe("2026-11-30");
    // A shifted December monthly (Mon 28 Dec) is still the quarterly.
    expect(isoOf(rows.Quarterly)).toBe("2026-12-28");
  });
});

describe("computeExpiries: incomplete lists", () => {
  it("leaves monthly and quarterly empty rather than guess from a short list", () => {
    const rows = rowsAt(["24-NOV-26"], SUNDAY_MORNING);
    expect(isoOf(rows.Weekly)).toBe("2026-11-24");
    expect(rows.Monthly).toBeNull();
    expect(rows.Quarterly).toBeNull();
  });

  it("returns no dates for an empty or unparseable list", () => {
    const rows = rowsAt(["", "not-a-date"], SUNDAY_MORNING);
    expect(Object.values(rows)).toEqual([null, null, null]);
  });

  it("does not depend on the host timezone", () => {
    // 23:30 UTC on 23 Nov is already 05:00 IST on Tue 24 Nov, expiry day.
    expect(isoOf(rowsAt(NIFTY_LIST, "2026-11-23T23:30:00Z").Weekly)).toBe("2026-11-24");
  });
});

describe("ExpiryCountdownWidget", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date(SUNDAY_MORNING));
    apiMocks.getExpiry.mockReset();
    apiMocks.getExpiry.mockImplementation(async (symbol: string) => ({
      expiry: symbol === "SENSEX" ? SENSEX_LIST : NIFTY_LIST,
    }));
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("renders the header, IST clock, legend and container label", async () => {
    render(<ExpiryCountdownWidget />);
    await flush();
    expect(screen.getByText("Expiry Countdown")).toBeTruthy();
    expect(screen.getByText(/IST$/)).toBeTruthy();
    expect(screen.getByText(/> 7d/)).toBeTruthy();
    expect(screen.getByText(/< 1d/)).toBeTruthy();
    expect(screen.getByLabelText("Options Expiry Countdown widget")).toBeTruthy();
  });

  it("loads the NIFTY list from the NSE option segment by default", async () => {
    render(<ExpiryCountdownWidget />);
    await flush();
    expect(apiMocks.getExpiry).toHaveBeenCalledWith("NIFTY", "NFO", "options", expect.any(AbortSignal));
    const items = screen.getAllByRole("listitem");
    expect(items).toHaveLength(3);
    expect(screen.getAllByText("Expires Tue 24 Nov")).toHaveLength(2);
    expect(screen.getByText("Expires Tue 29 Dec")).toBeInTheDocument();
    expect(screen.getByText("Dates from the NSE NIFTY contract list.")).toBeInTheDocument();
  });

  it("switches to SENSEX and shows its Thursday expiries", async () => {
    render(<ExpiryCountdownWidget />);
    await flush();
    fireEvent.click(screen.getByRole("button", { name: "SENSEX" }));
    await flush();
    expect(apiMocks.getExpiry).toHaveBeenLastCalledWith("SENSEX", "BFO", "options", expect.any(AbortSignal));
    expect(screen.getAllByText("Expires Thu 26 Nov")).toHaveLength(2);
    expect(screen.getByText("Expires Thu 31 Dec")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "SENSEX" })).toHaveAttribute("aria-pressed", "true");
  });

  it("never shows an assumed weekday", async () => {
    render(<ExpiryCountdownWidget />);
    await flush();
    expect(screen.queryByText(/Assumed/)).toBeNull();
    expect(screen.queryByText(/assumption/i)).toBeNull();
  });

  it("says the list could not load instead of guessing dates", async () => {
    apiMocks.getExpiry.mockRejectedValue(new Error("network"));
    render(<ExpiryCountdownWidget />);
    await flush();
    expect(screen.queryAllByRole("listitem")).toHaveLength(0);
    expect(screen.getByRole("status")).toHaveTextContent(/^Couldn.t load the NIFTY expiry list\.$/);
  });

  it("names SENSEX when the SENSEX list cannot load", async () => {
    render(<ExpiryCountdownWidget />);
    await flush();
    apiMocks.getExpiry.mockRejectedValue(new Error("network"));
    fireEvent.click(screen.getByRole("button", { name: "SENSEX" }));
    await flush();
    expect(screen.getByRole("status")).toHaveTextContent(/^Couldn.t load the SENSEX expiry list\.$/);
  });

  it("gives each underlying toggle a 44px tall target", async () => {
    render(<ExpiryCountdownWidget />);
    await flush();
    for (const name of ["NIFTY", "SENSEX"]) {
      expect(screen.getByRole("button", { name })).toHaveClass("min-h-11");
    }
  });

  it("marks a contract the list does not carry as not listed", async () => {
    apiMocks.getExpiry.mockResolvedValue({ expiry: ["24-NOV-26"] });
    render(<ExpiryCountdownWidget />);
    await flush();
    expect(screen.getByText("Expires Tue 24 Nov")).toBeInTheDocument();
    expect(screen.getAllByText("Not listed")).toHaveLength(2);
  });

  it("keeps ticking after the list loads", async () => {
    render(<ExpiryCountdownWidget />);
    await flush();
    const before = screen.getAllByRole("listitem")[0].textContent;
    act(() => {
      vi.advanceTimersByTime(1000);
    });
    expect(screen.getAllByRole("listitem")[0].textContent).not.toBe(before);
  });
});
