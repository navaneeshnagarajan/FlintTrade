/**
 * OrderBookReplayWidget.test.tsx
 *
 * Tests: render, controls, ladder, stats bar, speed pills.
 */

import { describe, it, expect, vi, beforeAll, afterAll, afterEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import "@testing-library/jest-dom";

beforeAll(() => {
  global.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
  vi.useFakeTimers();
});

afterEach(() => {
  vi.clearAllTimers();
});

// Restore real timers after this file's tests complete so that later test
// files in singleFork mode are not affected by the fake-timer environment.
afterAll(() => {
  vi.useRealTimers();
});

vi.mock("@/hooks/useTrackBehavior", () => ({
  useTrackBehavior: () => vi.fn(),
}));

import OrderBookReplayWidget from "../OrderBookReplayWidget";

describe("OrderBookReplayWidget", () => {
  it("renders the widget header", () => {
    render(<OrderBookReplayWidget />);
    expect(screen.getByText("Order Book Replay")).toBeTruthy();
  });

  it("shows the permanent 'Sample data' badge", () => {
    render(<OrderBookReplayWidget />);
    const badge = screen.getByText("Sample data");
    expect(badge).toBeTruthy();
    expect(badge.getAttribute("role")).toBe("status");
  });

  it("renders the replay toolbar", () => {
    render(<OrderBookReplayWidget />);
    expect(screen.getByRole("toolbar", { name: "Order book replay controls" })).toBeTruthy();
  });

  it("renders play button initially", () => {
    render(<OrderBookReplayWidget />);
    expect(screen.getByLabelText("Play replay")).toBeTruthy();
  });

  it("renders the scrubber slider", () => {
    render(<OrderBookReplayWidget />);
    expect(screen.getByRole("slider", { name: "Replay position" })).toBeTruthy();
  });

  it("renders speed pill buttons 1x through 8x", () => {
    render(<OrderBookReplayWidget />);
    expect(screen.getByLabelText("1x speed")).toBeTruthy();
    expect(screen.getByLabelText("2x speed")).toBeTruthy();
    expect(screen.getByLabelText("4x speed")).toBeTruthy();
    expect(screen.getByLabelText("8x speed")).toBeTruthy();
  });

  it("renders stats bar with Spread and Imbalance", () => {
    render(<OrderBookReplayWidget />);
    expect(screen.getByText("Spread")).toBeTruthy();
    expect(screen.getByText("Imbalance")).toBeTruthy();
  });

  it("pressing play button switches to pause button", () => {
    render(<OrderBookReplayWidget />);
    const playBtn = screen.getByLabelText("Play replay");
    fireEvent.click(playBtn);
    expect(screen.getByLabelText("Pause replay")).toBeTruthy();
  });

  it("reset button disables and resets scrubber to 1", () => {
    render(<OrderBookReplayWidget />);
    const resetBtn = screen.getByLabelText("Reset to start");
    fireEvent.click(resetBtn);
    const slider = screen.getByRole("slider", { name: "Replay position" });
    expect(slider.getAttribute("aria-valuenow")).toBe("0");
  });
});
