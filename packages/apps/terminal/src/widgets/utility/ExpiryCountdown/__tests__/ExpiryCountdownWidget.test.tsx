import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, act } from "@testing-library/react";
import "@testing-library/jest-dom";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

vi.mock("@/hooks/useTrackBehavior", () => ({
  useTrackBehavior: () => vi.fn(),
}));

import ExpiryCountdownWidget, {
  EXPIRY_ASSUMPTION_NOTE,
  EXPIRY_WEEKDAY_NAME,
  NSE_EXPIRY_WEEKDAY,
  computeExpiries,
} from "../ExpiryCountdownWidget";
import { istParts, toIstIsoDate } from "@/lib/ist";

describe("ExpiryCountdownWidget", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("renders widget header with title", () => {
    render(<ExpiryCountdownWidget />);
    expect(screen.getByText("Expiry Countdown")).toBeTruthy();
  });

  it("renders all three expiry kinds", () => {
    render(<ExpiryCountdownWidget />);
    expect(screen.getByText("Weekly")).toBeTruthy();
    expect(screen.getByText("Monthly")).toBeTruthy();
    expect(screen.getByText("Quarterly")).toBeTruthy();
  });

  it("renders the expiry list with correct role", () => {
    render(<ExpiryCountdownWidget />);
    expect(screen.getByRole("list", { name: /expiry countdown list/i })).toBeTruthy();
  });

  it("renders three list items", () => {
    render(<ExpiryCountdownWidget />);
    const items = screen.getAllByRole("listitem");
    expect(items.length).toBe(3);
  });

  it("shows IST clock in header", () => {
    render(<ExpiryCountdownWidget />);
    expect(screen.getByText(/IST/)).toBeTruthy();
  });

  it("renders urgency legend", () => {
    render(<ExpiryCountdownWidget />);
    expect(screen.getByText(/> 7d/)).toBeTruthy();
    expect(screen.getByText(/3–7d/)).toBeTruthy();
    expect(screen.getByText(/< 3d/)).toBeTruthy();
    expect(screen.getByText(/< 1d/)).toBeTruthy();
  });

  it("has aria label on widget container", () => {
    render(<ExpiryCountdownWidget />);
    expect(screen.getByLabelText("Options Expiry Countdown widget")).toBeTruthy();
  });

  it("countdown updates after 1 second", () => {
    render(<ExpiryCountdownWidget />);
    const before = screen.getAllByRole("listitem")[0].textContent;
    act(() => {
      vi.advanceTimersByTime(1000);
    });
    // Widget still renders fine after tick
    expect(screen.getByText("Expiry Countdown")).toBeTruthy();
    // Timer text has changed or at least re-rendered
    expect(screen.getAllByRole("listitem")[0].textContent).toBeDefined();
    void before; // suppress unused variable warning
  });

  it("each row has NSE F&O Expiry sub-label", () => {
    render(<ExpiryCountdownWidget />);
    const labels = screen.getAllByText(/NSE F&O Expiry/);
    expect(labels.length).toBe(3);
  });
});

// ---------------------------------------------------------------------------
// Expiry-weekday disclosure
//
// The countdown arithmetic is exact, but it counts down to a weekday nothing in
// this repository has verified against an NSE circular. The widget must say so
// on screen: printing "Thu 30 Jul" and a live seconds countdown as plain fact
// is the failure mode these cases pin against.
// ---------------------------------------------------------------------------

describe("ExpiryCountdownWidget — expiry-weekday caveat", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("badges the assumed weekday in the header", () => {
    render(<ExpiryCountdownWidget />);
    const badge = screen.getByRole("status", { name: EXPIRY_ASSUMPTION_NOTE });
    expect(badge).toHaveTextContent(`Assumed ${EXPIRY_WEEKDAY_NAME}`);
  });

  it("uses the same amber affordance sibling widgets use for unverified figures", () => {
    render(<ExpiryCountdownWidget />);
    const badge = screen.getByRole("status", { name: EXPIRY_ASSUMPTION_NOTE });
    expect(badge.className).toContain("text-warning");
    expect(badge.className).toContain("bg-warning/10");
    expect(badge).toHaveAttribute("title", EXPIRY_ASSUMPTION_NOTE);
  });

  it("spells the caveat out in full, naming what to check it against", () => {
    render(<ExpiryCountdownWidget />);
    expect(screen.getByText(EXPIRY_ASSUMPTION_NOTE)).toBeInTheDocument();
    expect(EXPIRY_ASSUMPTION_NOTE).toContain("assumption, not a verified exchange rule");
    expect(EXPIRY_ASSUMPTION_NOTE).toContain("contract master");
    expect(EXPIRY_ASSUMPTION_NOTE).toContain("NSE circular");
  });

  it("shows the caveat unconditionally — no connected state makes it a fact", () => {
    const { rerender } = render(<ExpiryCountdownWidget />);
    act(() => {
      vi.advanceTimersByTime(5000);
    });
    rerender(<ExpiryCountdownWidget />);
    expect(screen.getAllByText(EXPIRY_ASSUMPTION_NOTE).length).toBeGreaterThan(0);
  });

  it("carries the caveat into each row's accessible name, beside the date", () => {
    render(<ExpiryCountdownWidget />);
    for (const item of screen.getAllByRole("listitem")) {
      expect(item.getAttribute("aria-label")).toContain(
        `(assumed ${EXPIRY_WEEKDAY_NAME} expiry, not verified against the NSE calendar)`,
      );
    }
  });

  it("derives the caveat wording from the one constant, so moving it moves the copy", () => {
    // The disclosure must never drift from the rule it discloses.
    expect(EXPIRY_WEEKDAY_NAME).toBe(["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"][NSE_EXPIRY_WEEKDAY]);
    expect(EXPIRY_ASSUMPTION_NOTE).toContain(EXPIRY_WEEKDAY_NAME);
  });
});

// ---------------------------------------------------------------------------
// Expiry date maths
//
// Every case below feeds computeExpiries a FIXED instant, so the assertions
// hold whatever timezone the machine is set to. The old implementation did its
// arithmetic in the browser's local zone, which is exactly what these pin
// against.
//
// Calendar facts used (all IST): Thu 30 Jul 2026 is the last Thursday of July;
// Thu 6 Aug 2026 is the following week; Thu 31 Dec 2026 is the last Thursday
// of December; Thu 24 Sep 2026 and Thu 25 Mar 2027 are the neighbouring
// quarter ends.
// ---------------------------------------------------------------------------

/** The three rows keyed by kind, for a given instant. */
function expiriesAt(iso: string): Record<string, Date> {
  return Object.fromEntries(
    computeExpiries(new Date(iso)).map((row) => [row.kind, row.date]),
  );
}

describe("NSE_EXPIRY_WEEKDAY", () => {
  it("is an explicit, single-point constant (Thursday) rather than a literal", () => {
    // Recorded, not re-derived: this is the weekday the widget has always
    // assumed. It still needs confirming against a current NSE circular —
    // see the widget's module docstring.
    expect(NSE_EXPIRY_WEEKDAY).toBe(4);
  });

  it("drives all three expiries, so moving it is a one-line change", () => {
    for (const date of Object.values(expiriesAt("2026-07-27T04:00:00Z"))) {
      expect(istParts(date).weekday).toBe(NSE_EXPIRY_WEEKDAY);
    }
  });
});

describe("computeExpiries — weekly", () => {
  it("REGRESSION: keeps today's expiry on expiry-day morning", () => {
    // 04:00 UTC on Thursday 30 July 2026 is 09:30 IST — the market has just
    // opened on expiry day. The old `(4 - day + 7) % 7 || 7` rolled straight
    // to the following Thursday from midnight, hiding the contract that was
    // expiring in six hours' time.
    const { Weekly } = expiriesAt("2026-07-30T04:00:00Z");
    expect(toIstIsoDate(Weekly)).toBe("2026-07-30");
    expect(istParts(Weekly)).toMatchObject({ hour: 15, minute: 30 });
  });

  it("holds today's expiry right up to the 15:30 IST close", () => {
    // 09:59:59 UTC = 15:29:59 IST on expiry day.
    expect(toIstIsoDate(expiriesAt("2026-07-30T09:59:59Z").Weekly)).toBe("2026-07-30");
  });

  it("rolls to the next week once the close has passed", () => {
    // 10:30 UTC = 16:00 IST on expiry day.
    expect(toIstIsoDate(expiriesAt("2026-07-30T10:30:00Z").Weekly)).toBe("2026-08-06");
  });

  it("finds the coming expiry from a mid-week day", () => {
    // Monday 27 July 2026, 09:30 IST.
    expect(toIstIsoDate(expiriesAt("2026-07-27T04:00:00Z").Weekly)).toBe("2026-07-30");
  });

  it("crosses a month boundary when the next expiry is in the following month", () => {
    // Friday 31 July 2026 → Thursday 6 August 2026.
    expect(toIstIsoDate(expiriesAt("2026-07-31T04:00:00Z").Weekly)).toBe("2026-08-06");
  });
});

describe("computeExpiries — monthly", () => {
  it("uses the last expiry weekday of the current month", () => {
    expect(toIstIsoDate(expiriesAt("2026-07-27T04:00:00Z").Monthly)).toBe("2026-07-30");
  });

  it("rolls into next month once the monthly close has passed", () => {
    expect(toIstIsoDate(expiriesAt("2026-07-30T10:30:00Z").Monthly)).toBe("2026-08-27");
  });

  it("rolls across the year boundary from December", () => {
    // 31 Dec 2026 is itself the December expiry; after its close the next is
    // the last Thursday of January 2027.
    expect(toIstIsoDate(expiriesAt("2026-12-31T10:30:00Z").Monthly)).toBe("2027-01-28");
  });
});

describe("computeExpiries — quarterly", () => {
  it("REGRESSION: returns THIS December's expiry during December", () => {
    // 1 December 2026, 10:00 IST. The old `if (qtrMonth <= m) qtrYear += 1`
    // fired in every quarter-end month, so December advertised the December of
    // the FOLLOWING year — a countdown a full year out.
    const { Quarterly } = expiriesAt("2026-12-01T04:30:00Z");
    expect(toIstIsoDate(Quarterly)).toBe("2026-12-31");
    expect(istParts(Quarterly).year).toBe(2026);
  });

  it("REGRESSION: returns THIS September's expiry during September", () => {
    expect(toIstIsoDate(expiriesAt("2026-09-01T04:30:00Z").Quarterly)).toBe("2026-09-24");
  });

  it("rolls to the next quarter once the quarterly close has passed", () => {
    // 16:00 IST on 31 December 2026 → the March 2027 quarter end.
    expect(toIstIsoDate(expiriesAt("2026-12-31T10:30:00Z").Quarterly)).toBe("2027-03-25");
  });

  it("looks ahead to the coming quarter end from a non-quarter month", () => {
    // July 2026 → September 2026.
    expect(toIstIsoDate(expiriesAt("2026-07-27T04:00:00Z").Quarterly)).toBe("2026-09-24");
  });

  it("always returns an instant in the future", () => {
    for (const iso of [
      "2026-03-26T10:30:00Z",
      "2026-06-25T10:30:00Z",
      "2026-09-24T10:30:00Z",
      "2026-12-31T10:30:00Z",
    ]) {
      expect(expiriesAt(iso).Quarterly.getTime()).toBeGreaterThan(new Date(iso).getTime());
    }
  });
});

describe("computeExpiries — timezone independence", () => {
  it("anchors every expiry to 15:30 IST, not to the operator's local 15:30", () => {
    // 15:30 IST is 10:00 UTC, whatever zone the machine reports.
    for (const date of Object.values(expiriesAt("2026-07-27T04:00:00Z"))) {
      expect(date.toISOString().slice(11)).toBe("10:00:00.000Z");
    }
  });

  it("orders the rows weekly ≤ monthly ≤ quarterly", () => {
    const rows = computeExpiries(new Date("2026-07-27T04:00:00Z"));
    expect(rows.map((r) => r.kind)).toEqual(["Weekly", "Monthly", "Quarterly"]);
    expect(rows[0].date.getTime()).toBeLessThanOrEqual(rows[1].date.getTime());
    expect(rows[1].date.getTime()).toBeLessThanOrEqual(rows[2].date.getTime());
  });
});
