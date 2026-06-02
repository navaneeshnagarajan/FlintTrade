import { describe, it, expect, vi, beforeAll } from "vitest";
import { render, screen } from "@testing-library/react";

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
import RiskDashboardWidget, {
  SAMPLE_RISK_DATA,
} from "../RiskDashboardWidget";

import type { TrafficLight } from "../RiskDashboardWidget";

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

describe("RiskDashboardWidget", () => {
  it("renders widget title", () => {
    mockConnected.mockReturnValue(false);
    render(<RiskDashboardWidget />);
    expect(screen.getByText("Risk Dashboard")).toBeTruthy();
  });

  it("shows Sample badge when disconnected", () => {
    mockConnected.mockReturnValue(false);
    render(<RiskDashboardWidget />);
    expect(screen.getByText("Sample")).toBeTruthy();
  });

  it("does not show Sample badge when connected", () => {
    mockConnected.mockReturnValue(true);
    render(<RiskDashboardWidget />);
    expect(screen.queryByText("Sample")).toBeNull();
  });

  it("renders overall status banner", () => {
    mockConnected.mockReturnValue(false);
    render(<RiskDashboardWidget />);
    const banner = screen.getByLabelText(/Overall risk status/i);
    expect(banner).toBeTruthy();
  });

  it("renders risk metrics section", () => {
    mockConnected.mockReturnValue(false);
    render(<RiskDashboardWidget />);
    expect(screen.getByLabelText("Risk metrics")).toBeTruthy();
  });

  it("renders all sample metric labels", () => {
    mockConnected.mockReturnValue(false);
    render(<RiskDashboardWidget />);
    for (const m of SAMPLE_RISK_DATA.metrics) {
      expect(screen.getByText(m.label)).toBeTruthy();
    }
  });

  it("renders legend with three traffic light levels", () => {
    mockConnected.mockReturnValue(false);
    render(<RiskDashboardWidget />);
    expect(screen.getByText(/Within limits/i)).toBeTruthy();
    expect(screen.getByText(/Approaching/i)).toBeTruthy();
    expect(screen.getByText(/Breached/i)).toBeTruthy();
  });

  it("renders metric cards with aria labels", () => {
    mockConnected.mockReturnValue(false);
    render(<RiskDashboardWidget />);
    for (const m of SAMPLE_RISK_DATA.metrics) {
      const card = screen.getByLabelText(new RegExp(m.label, "i"));
      expect(card).toBeTruthy();
    }
  });

  it("renders metric gauges through the shared Flint radial gauge primitive", () => {
    mockConnected.mockReturnValue(false);
    const { container } = render(<RiskDashboardWidget />);
    const gauges = container.querySelectorAll('[data-flint-chart="radial-gauge"]');
    expect(gauges.length).toBe(SAMPLE_RISK_DATA.metrics.length);
  });
});

// ---------------------------------------------------------------------------
// Sample data / logic tests
// ---------------------------------------------------------------------------

describe("SAMPLE_RISK_DATA", () => {
  it("has 5 metrics", () => {
    expect(SAMPLE_RISK_DATA.metrics).toHaveLength(5);
  });

  it("each metric has a valid traffic light level", () => {
    const valid: TrafficLight[] = ["green", "amber", "red"];
    for (const m of SAMPLE_RISK_DATA.metrics) {
      expect(valid).toContain(m.level);
    }
  });

  it("usagePct is between 0 and 100 for all metrics", () => {
    for (const m of SAMPLE_RISK_DATA.metrics) {
      expect(m.usagePct).toBeGreaterThanOrEqual(0);
      expect(m.usagePct).toBeLessThanOrEqual(100);
    }
  });

  it("margin metric has percentage unit", () => {
    const margin = SAMPLE_RISK_DATA.metrics.find((m) => m.id === "margin");
    expect(margin).toBeDefined();
    expect(margin?.unit).toBe("%");
  });

  it("overall level is the worst of individual levels", () => {
    const hasRed  = SAMPLE_RISK_DATA.metrics.some((m) => m.level === "red");
    const hasAmber = SAMPLE_RISK_DATA.metrics.some((m) => m.level === "amber");
    if (hasRed) {
      expect(SAMPLE_RISK_DATA.overallLevel).toBe("red");
    } else if (hasAmber) {
      expect(SAMPLE_RISK_DATA.overallLevel).toBe("amber");
    } else {
      expect(SAMPLE_RISK_DATA.overallLevel).toBe("green");
    }
  });

  it("all metric ids are unique", () => {
    const ids = SAMPLE_RISK_DATA.metrics.map((m) => m.id);
    const unique = new Set(ids);
    expect(unique.size).toBe(ids.length);
  });
});
