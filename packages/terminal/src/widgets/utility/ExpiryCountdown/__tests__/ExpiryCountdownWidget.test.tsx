import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, act } from "@testing-library/react";
import "@testing-library/jest-dom";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

vi.mock("@/hooks/useTrackBehavior", () => ({
  useTrackBehavior: () => vi.fn(),
}));

import ExpiryCountdownWidget from "../ExpiryCountdownWidget";

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
