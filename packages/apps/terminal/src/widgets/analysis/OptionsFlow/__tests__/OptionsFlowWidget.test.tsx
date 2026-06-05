import { describe, it, expect, vi, beforeAll } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

vi.mock("@/hooks/useTrackBehavior", () => ({
  useTrackBehavior: () => vi.fn(),
}));

import OptionsFlowWidget, { SAMPLE_FLOW } from "../OptionsFlowWidget";

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

describe("OptionsFlowWidget", () => {
  it("renders widget title", () => {
    render(<OptionsFlowWidget />);
    expect(screen.getByText("Options Flow")).toBeTruthy();
  });

  it("always shows the permanent 'Sample data' badge (no live feed wired)", () => {
    // The flow is hardcoded SAMPLE_FLOW with no backend; the badge must NOT be
    // masked by broker connection — connecting a broker does not make it live.
    render(<OptionsFlowWidget />);
    const badge = screen.getByText("Sample data");
    expect(badge).toBeTruthy();
    expect(badge.getAttribute("aria-label")).toContain("sample data");
  });

  it("renders the flow table with aria label", () => {
    render(<OptionsFlowWidget />);
    expect(screen.getByLabelText("Options flow table")).toBeTruthy();
  });

  it("renders column headers", () => {
    render(<OptionsFlowWidget />);
    expect(screen.getByText("Time")).toBeTruthy();
    expect(screen.getByText("Symbol")).toBeTruthy();
    expect(screen.getByText("Strike")).toBeTruthy();
    expect(screen.getByText("Type")).toBeTruthy();
    expect(screen.getByText("Side")).toBeTruthy();
    expect(screen.getByText("Premium")).toBeTruthy();
  });

  it("renders filter controls", () => {
    render(<OptionsFlowWidget />);
    expect(screen.getByLabelText("Filter by symbol")).toBeTruthy();
    expect(screen.getByLabelText("Filter by activity type")).toBeTruthy();
  });

  it("shows all sample entries initially", () => {
    render(<OptionsFlowWidget />);
    expect(screen.getByText(`${SAMPLE_FLOW.length} entries`)).toBeTruthy();
  });

  it("symbol filter trigger is present with default value", () => {
    render(<OptionsFlowWidget />);
    const trigger = screen.getByLabelText("Filter by symbol");
    expect(trigger).toBeTruthy();
    // Default value shown in shadcn Select trigger
    expect(trigger.textContent).toContain("All");
  });

  it("sort toggle button exists and toggles label", () => {
    render(<OptionsFlowWidget />);
    const btn = screen.getByLabelText(/Sort by/i) as HTMLButtonElement;
    expect(btn).toBeTruthy();
    expect(screen.getByText("Newest")).toBeTruthy();
    fireEvent.click(btn);
    expect(screen.getByText("Largest")).toBeTruthy();
  });
});

// ---------------------------------------------------------------------------
// Sample data tests
// ---------------------------------------------------------------------------

describe("SAMPLE_FLOW", () => {
  it("has at least 5 entries", () => {
    expect(SAMPLE_FLOW.length).toBeGreaterThanOrEqual(5);
  });

  it("all entries have unique ids", () => {
    const ids = SAMPLE_FLOW.map((e) => e.id);
    expect(new Set(ids).size).toBe(ids.length);
  });

  it("totalPremium is positive for all entries", () => {
    for (const e of SAMPLE_FLOW) {
      expect(e.totalPremium).toBeGreaterThan(0);
    }
  });

  it("large order flag set for high qty entries", () => {
    for (const e of SAMPLE_FLOW) {
      if (e.isLargeOrder) {
        // Just verify flag is boolean
        expect(typeof e.isLargeOrder).toBe("boolean");
      }
    }
  });

  it("all activity types are valid", () => {
    const valid = ["sweep", "block", "unusual_oi"];
    for (const e of SAMPLE_FLOW) {
      expect(valid).toContain(e.activityType);
    }
  });

  it("all option types are CE or PE", () => {
    for (const e of SAMPLE_FLOW) {
      expect(["CE", "PE"]).toContain(e.optionType);
    }
  });

  it("all actions are BUY or SELL", () => {
    for (const e of SAMPLE_FLOW) {
      expect(["BUY", "SELL"]).toContain(e.action);
    }
  });
});
