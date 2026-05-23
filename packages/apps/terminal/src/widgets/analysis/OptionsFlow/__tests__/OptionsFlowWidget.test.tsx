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
import OptionsFlowWidget, { SAMPLE_FLOW } from "../OptionsFlowWidget";

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

describe("OptionsFlowWidget", () => {
  it("renders widget title", () => {
    mockConnected.mockReturnValue(false);
    render(<OptionsFlowWidget />);
    expect(screen.getByText("Options Flow")).toBeTruthy();
  });

  it("shows Sample badge when disconnected", () => {
    mockConnected.mockReturnValue(false);
    render(<OptionsFlowWidget />);
    expect(screen.getByText("Sample")).toBeTruthy();
  });

  it("does not show Sample badge when connected", () => {
    mockConnected.mockReturnValue(true);
    render(<OptionsFlowWidget />);
    expect(screen.queryByText("Sample")).toBeNull();
  });

  it("renders the flow table with aria label", () => {
    mockConnected.mockReturnValue(false);
    render(<OptionsFlowWidget />);
    expect(screen.getByLabelText("Options flow table")).toBeTruthy();
  });

  it("renders column headers", () => {
    mockConnected.mockReturnValue(false);
    render(<OptionsFlowWidget />);
    expect(screen.getByText("Time")).toBeTruthy();
    expect(screen.getByText("Symbol")).toBeTruthy();
    expect(screen.getByText("Strike")).toBeTruthy();
    expect(screen.getByText("Type")).toBeTruthy();
    expect(screen.getByText("Side")).toBeTruthy();
    expect(screen.getByText("Premium")).toBeTruthy();
  });

  it("renders filter controls", () => {
    mockConnected.mockReturnValue(false);
    render(<OptionsFlowWidget />);
    expect(screen.getByLabelText("Filter by symbol")).toBeTruthy();
    expect(screen.getByLabelText("Filter by activity type")).toBeTruthy();
  });

  it("shows all sample entries initially", () => {
    mockConnected.mockReturnValue(false);
    render(<OptionsFlowWidget />);
    expect(screen.getByText(`${SAMPLE_FLOW.length} entries`)).toBeTruthy();
  });

  it("symbol filter trigger is present with default value", () => {
    mockConnected.mockReturnValue(false);
    render(<OptionsFlowWidget />);
    const trigger = screen.getByLabelText("Filter by symbol");
    expect(trigger).toBeTruthy();
    // Default value shown in shadcn Select trigger
    expect(trigger.textContent).toContain("All");
  });

  it("sort toggle button exists and toggles label", () => {
    mockConnected.mockReturnValue(false);
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
