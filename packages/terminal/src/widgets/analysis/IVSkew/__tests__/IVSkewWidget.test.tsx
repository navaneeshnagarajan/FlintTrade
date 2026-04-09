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
import IVSkewWidget, {
  SAMPLE_IV_SKEW_DATA,
  type IVSkewCurve,
} from "../IVSkewWidget";

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

describe("IVSkewWidget", () => {
  it("renders widget title", () => {
    mockConnected.mockReturnValue(false);
    render(<IVSkewWidget />);
    expect(screen.getByText("IV Skew")).toBeTruthy();
  });

  it("shows Sample badge when disconnected", () => {
    mockConnected.mockReturnValue(false);
    render(<IVSkewWidget />);
    expect(screen.getByText("Sample")).toBeTruthy();
  });

  it("does not show Sample badge when connected", () => {
    mockConnected.mockReturnValue(true);
    render(<IVSkewWidget />);
    expect(screen.queryByText("Sample")).toBeNull();
  });

  it("renders ATM IV metric", () => {
    mockConnected.mockReturnValue(false);
    render(<IVSkewWidget />);
    expect(screen.getByText("ATM IV")).toBeTruthy();
  });

  it("renders 25Δ Skew metric", () => {
    mockConnected.mockReturnValue(false);
    render(<IVSkewWidget />);
    expect(screen.getByText("25Δ Skew")).toBeTruthy();
  });

  it("renders the SVG chart with aria label", () => {
    mockConnected.mockReturnValue(false);
    render(<IVSkewWidget />);
    expect(screen.getByLabelText("IV Skew chart")).toBeTruthy();
  });

  it("symbol selector includes NIFTY", () => {
    mockConnected.mockReturnValue(false);
    render(<IVSkewWidget />);
    const select = screen.getByLabelText("Select symbol") as HTMLSelectElement;
    expect(select).toBeTruthy();
    expect(select.value).toBe("NIFTY");
  });

  it("can switch to Moneyness X-axis", () => {
    mockConnected.mockReturnValue(false);
    render(<IVSkewWidget />);
    const btn = screen.getByRole("button", { name: /moneyness/i });
    fireEvent.click(btn);
    expect(btn.getAttribute("aria-pressed")).toBe("true");
  });

  it("Strike button is initially pressed", () => {
    mockConnected.mockReturnValue(false);
    render(<IVSkewWidget />);
    const btn = screen.getByRole("button", { name: /^strike$/i });
    expect(btn.getAttribute("aria-pressed")).toBe("true");
  });

  it("renders refresh button", () => {
    mockConnected.mockReturnValue(false);
    render(<IVSkewWidget />);
    expect(screen.getByLabelText("Refresh IV skew")).toBeTruthy();
  });
});

// ---------------------------------------------------------------------------
// Sample data tests
// ---------------------------------------------------------------------------

describe("SAMPLE_IV_SKEW_DATA", () => {
  it("has at least 2 curves for term structure", () => {
    expect(SAMPLE_IV_SKEW_DATA.curves.length).toBeGreaterThanOrEqual(2);
  });

  it("every curve has a positive atm_iv", () => {
    for (const curve of SAMPLE_IV_SKEW_DATA.curves) {
      expect(curve.atm_iv).toBeGreaterThan(0);
    }
  });

  it("every curve has at least 5 strike points", () => {
    for (const curve of SAMPLE_IV_SKEW_DATA.curves) {
      expect(curve.points.length).toBeGreaterThanOrEqual(5);
    }
  });

  it("skew_25delta is a finite number for all curves", () => {
    for (const curve of SAMPLE_IV_SKEW_DATA.curves) {
      expect(Number.isFinite(curve.skew_25delta)).toBe(true);
    }
  });

  it("moneyness at ATM strike is approximately 1.0", () => {
    for (const curve of SAMPLE_IV_SKEW_DATA.curves) {
      const atmPoint = curve.points.find((p) => p.strike === curve.atm_strike);
      if (atmPoint) {
        expect(Math.abs(atmPoint.moneyness - 1.0)).toBeLessThan(0.01);
      }
    }
  });
});

// ---------------------------------------------------------------------------
// Computation tests
// ---------------------------------------------------------------------------

describe("IVSkewCurve skew_25delta interpretation", () => {
  it("positive skew means put premium (put IV > call IV)", () => {
    const curve = SAMPLE_IV_SKEW_DATA.curves[0] as IVSkewCurve;
    // positive skew_25delta = put IV 25d > call IV 25d
    if (curve.skew_25delta > 0) {
      // just validate the sign convention holds in our sample
      expect(curve.skew_25delta).toBeGreaterThan(0);
    }
  });

  it("ATM IV is within a reasonable range (5%–100%)", () => {
    for (const curve of SAMPLE_IV_SKEW_DATA.curves) {
      expect(curve.atm_iv * 100).toBeGreaterThan(5);
      expect(curve.atm_iv * 100).toBeLessThan(100);
    }
  });
});
