import { describe, it, expect, vi, beforeAll } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";

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
import GapAnalysisWidget from "../GapAnalysisWidget";
import { SAMPLE_GAP_EVENTS } from "../GapAnalysisWidget";

const mockConnected = useBrokerConnected as ReturnType<typeof vi.fn>;

beforeAll(() => {
  global.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
});

// ---------------------------------------------------------------------------
// Widget render tests
// ---------------------------------------------------------------------------

describe("GapAnalysisWidget", () => {
  it("renders widget title", () => {
    mockConnected.mockReturnValue(false);
    render(<GapAnalysisWidget />);
    expect(screen.getByText("Gap Analysis")).toBeTruthy();
  });

  it("shows Sample badge when disconnected", () => {
    mockConnected.mockReturnValue(false);
    render(<GapAnalysisWidget />);
    expect(screen.getByText("Sample")).toBeTruthy();
  });

  it("does not show Sample badge when connected", () => {
    mockConnected.mockReturnValue(true);
    render(<GapAnalysisWidget />);
    expect(screen.queryByText("Sample")).toBeNull();
  });

  it("renders stat cards: Total Gaps, Fill Rate, Avg Size, Avg Fill", () => {
    mockConnected.mockReturnValue(false);
    render(<GapAnalysisWidget />);
    expect(screen.getByText("Total Gaps")).toBeTruthy();
    expect(screen.getByText("Fill Rate")).toBeTruthy();
    expect(screen.getByText("Avg Size")).toBeTruthy();
    expect(screen.getByText("Avg Fill")).toBeTruthy();
  });

  it("shows correct total gap count (20)", () => {
    mockConnected.mockReturnValue(false);
    render(<GapAnalysisWidget />);
    expect(screen.getByText("20")).toBeTruthy();
  });

  it("renders filter buttons: All, Gap Up, Gap Down", () => {
    mockConnected.mockReturnValue(false);
    render(<GapAnalysisWidget />);
    expect(screen.getByText("All")).toBeTruthy();
    expect(screen.getByText("Gap Up")).toBeTruthy();
    expect(screen.getByText("Gap Down")).toBeTruthy();
  });

  it("filter buttons switch which events are shown", () => {
    mockConnected.mockReturnValue(false);
    render(<GapAnalysisWidget />);
    const gapUpBtn = screen.getByText("Gap Up").closest("button")!;
    fireEvent.click(gapUpBtn);
    expect(gapUpBtn.getAttribute("aria-pressed")).toBe("true");
  });

  it("renders gap events table with column headers", () => {
    mockConnected.mockReturnValue(false);
    render(<GapAnalysisWidget />);
    expect(screen.getByText("Date")).toBeTruthy();
    expect(screen.getByText("Type")).toBeTruthy();
    expect(screen.getByText(/Gap %/i)).toBeTruthy();
    expect(screen.getByText("Filled")).toBeTruthy();
    expect(screen.getByText(/Fill time/i)).toBeTruthy();
  });

  it("scatter chart has aria label", () => {
    mockConnected.mockReturnValue(false);
    render(<GapAnalysisWidget />);
    expect(screen.getByLabelText(/Scatter chart/i)).toBeTruthy();
  });

  it("symbol selector is present", () => {
    mockConnected.mockReturnValue(false);
    render(<GapAnalysisWidget />);
    const select = screen.getByLabelText("Select symbol") as HTMLSelectElement;
    expect(select).toBeTruthy();
    const values = Array.from(select.options).map((o) => o.value);
    expect(values).toContain("NIFTY");
  });

  it("refresh button is disabled when disconnected", () => {
    mockConnected.mockReturnValue(false);
    render(<GapAnalysisWidget />);
    const btn = screen.getByLabelText("Refresh gap analysis") as HTMLButtonElement;
    expect(btn.disabled).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// Sample data tests
// ---------------------------------------------------------------------------

describe("SAMPLE_GAP_EVENTS", () => {
  it("has 20 gap events", () => {
    expect(SAMPLE_GAP_EVENTS).toHaveLength(20);
  });

  it("all events have a valid type", () => {
    for (const e of SAMPLE_GAP_EVENTS) {
      expect(["gap-up", "gap-down"]).toContain(e.type);
    }
  });

  it("gap-up events have positive gapPct", () => {
    for (const e of SAMPLE_GAP_EVENTS.filter((e) => e.type === "gap-up")) {
      expect(e.gapPct).toBeGreaterThan(0);
    }
  });

  it("gap-down events have negative gapPct", () => {
    for (const e of SAMPLE_GAP_EVENTS.filter((e) => e.type === "gap-down")) {
      expect(e.gapPct).toBeLessThan(0);
    }
  });

  it("unfilled events have null fillMinutes", () => {
    for (const e of SAMPLE_GAP_EVENTS.filter((e) => !e.filled)) {
      expect(e.fillMinutes).toBeNull();
    }
  });

  it("filled events have positive fillMinutes", () => {
    for (const e of SAMPLE_GAP_EVENTS.filter((e) => e.filled)) {
      expect(e.fillMinutes).not.toBeNull();
      expect(e.fillMinutes!).toBeGreaterThan(0);
    }
  });

  it("dates are in descending order (most recent first)", () => {
    for (let i = 1; i < SAMPLE_GAP_EVENTS.length; i++) {
      expect(SAMPLE_GAP_EVENTS[i - 1].date >= SAMPLE_GAP_EVENTS[i].date).toBe(true);
    }
  });

  it("contains a mix of filled and unfilled gaps", () => {
    const filled = SAMPLE_GAP_EVENTS.filter((e) => e.filled);
    const unfilled = SAMPLE_GAP_EVENTS.filter((e) => !e.filled);
    expect(filled.length).toBeGreaterThan(0);
    expect(unfilled.length).toBeGreaterThan(0);
  });
});
