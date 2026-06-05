import { describe, it, expect, vi, beforeAll } from "vitest";
import { render, screen } from "@testing-library/react";

// ---------------------------------------------------------------------------
// Mocks — inline selectors to avoid Zustand cast issues
// ---------------------------------------------------------------------------

vi.mock("@/hooks/useTrackBehavior", () => ({
  useTrackBehavior: () => vi.fn(),
}));

// Default: disconnected
vi.mock("@/stores/connectionStore", () => ({
  useConnectionStore: (selector: (s: { status: string }) => unknown) =>
    selector({ status: "disconnected" }),
}));

beforeAll(() => {
  global.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
});

import TickSpeedWidget, { deriveQuality, formatTickAge } from "../TickSpeedWidget";

// ---------------------------------------------------------------------------
// deriveQuality unit tests
// ---------------------------------------------------------------------------

describe("deriveQuality", () => {
  it("returns excellent for >= 50 tps", () => {
    expect(deriveQuality(50)).toBe("excellent");
    expect(deriveQuality(100)).toBe("excellent");
  });

  it("returns good for >= 20 and < 50 tps", () => {
    expect(deriveQuality(20)).toBe("good");
    expect(deriveQuality(49)).toBe("good");
  });

  it("returns fair for >= 5 and < 20 tps", () => {
    expect(deriveQuality(5)).toBe("fair");
    expect(deriveQuality(19)).toBe("fair");
  });

  it("returns poor for < 5 tps", () => {
    expect(deriveQuality(0)).toBe("poor");
    expect(deriveQuality(4)).toBe("poor");
  });
});

// ---------------------------------------------------------------------------
// formatTickAge unit tests
// ---------------------------------------------------------------------------

describe("formatTickAge", () => {
  it("returns an em dash when no tick has arrived", () => {
    expect(formatTickAge(-1)).toBe("—");
  });

  it("formats sub-second ages in milliseconds", () => {
    expect(formatTickAge(120)).toBe("120 ms");
  });

  it("formats ages over a second in seconds", () => {
    expect(formatTickAge(2500)).toBe("2.5 s");
  });
});

// ---------------------------------------------------------------------------
// Widget render tests
// ---------------------------------------------------------------------------

describe("TickSpeedWidget", () => {
  it("renders widget title", () => {
    render(<TickSpeedWidget />);
    expect(screen.getByText("Tick Speed")).toBeTruthy();
  });

  it("shows Sample badge when disconnected", () => {
    render(<TickSpeedWidget />);
    expect(screen.getByText("Sample")).toBeTruthy();
  });

  it("renders Ticks / second metric label", () => {
    render(<TickSpeedWidget />);
    expect(screen.getByText("Ticks / second")).toBeTruthy();
  });

  it("renders Last tick metric label", () => {
    render(<TickSpeedWidget />);
    expect(screen.getByText("Last tick")).toBeTruthy();
  });

  it("renders Reconnections metric label", () => {
    render(<TickSpeedWidget />);
    expect(screen.getByText("Reconnections")).toBeTruthy();
  });

  it("renders spark chart section heading", () => {
    render(<TickSpeedWidget />);
    expect(screen.getByText(/Tick rate/i)).toBeTruthy();
  });

  it("renders the tick rate chart through the shared Flint primitive", () => {
    render(<TickSpeedWidget />);
    const chart = screen.getByRole("img", { name: "Tick rate over last 5 minutes" });

    expect(chart).toHaveAttribute("viewBox", "0 0 160 42");
    expect(chart.querySelector("polyline")).not.toBeInTheDocument();
    expect(chart.querySelectorAll("path").length).toBeGreaterThan(0);
  });

  it("connection quality badge is rendered", () => {
    render(<TickSpeedWidget />);
    const badge = screen.getByLabelText(/Connection quality/i);
    expect(badge).toBeTruthy();
  });

  it("WifiOff icon aria-label present when disconnected", () => {
    render(<TickSpeedWidget />);
    expect(screen.getByLabelText("Disconnected")).toBeTruthy();
  });

  it("timeline labels 5m ago and now are present", () => {
    render(<TickSpeedWidget />);
    expect(screen.getByText("5m ago")).toBeTruthy();
    expect(screen.getByText("now")).toBeTruthy();
  });

  it("sample ticks/sec value renders as number", () => {
    render(<TickSpeedWidget />);
    // SAMPLE_METRICS.ticksPerSec = 84
    expect(screen.getByText("84")).toBeTruthy();
  });

  it("sample last-tick age renders", () => {
    render(<TickSpeedWidget />);
    // SAMPLE_METRICS.lastTickAgeMs = 120 → "120 ms"
    expect(screen.getByText("120 ms")).toBeTruthy();
  });
});
