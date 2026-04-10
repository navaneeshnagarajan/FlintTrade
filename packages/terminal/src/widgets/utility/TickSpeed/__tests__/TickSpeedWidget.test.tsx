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

import TickSpeedWidget, { deriveQuality } from "../TickSpeedWidget";

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

  it("renders Latency metric label", () => {
    render(<TickSpeedWidget />);
    expect(screen.getByText("Latency")).toBeTruthy();
  });

  it("renders Dropped metric label", () => {
    render(<TickSpeedWidget />);
    expect(screen.getByText("Dropped")).toBeTruthy();
  });

  it("renders Reconnections metric label", () => {
    render(<TickSpeedWidget />);
    expect(screen.getByText("Reconnections")).toBeTruthy();
  });

  it("renders spark chart section heading", () => {
    render(<TickSpeedWidget />);
    expect(screen.getByText(/Tick rate/i)).toBeTruthy();
  });

  it("spark chart SVG is rendered", () => {
    render(<TickSpeedWidget />);
    const svg = document.querySelector("svg");
    expect(svg).toBeTruthy();
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

  it("sample latency renders as number", () => {
    render(<TickSpeedWidget />);
    // SAMPLE_METRICS.latencyMs = 6
    expect(screen.getByText("6")).toBeTruthy();
  });
});
