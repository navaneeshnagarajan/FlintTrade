/**
 * NoConnectionOverlay.test.tsx — Renders connection warning with Settings button.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, act } from "@testing-library/react";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

let connectionStatus = "disconnected";

vi.mock("@/stores/connectionStore", () => ({
  useConnectionStore: (selector: (s: { status: string }) => unknown) =>
    selector({ status: connectionStatus }),
}));

const mockNavigate = vi.fn();
vi.mock("react-router-dom", () => ({
  useNavigate: () => mockNavigate,
  useLocation: () => ({ pathname: "/trade" }),
}));

// ---------------------------------------------------------------------------
// Import after mocks
// ---------------------------------------------------------------------------

import { NoConnectionOverlay } from "../NoConnectionOverlay";

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("NoConnectionOverlay", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    connectionStatus = "disconnected";
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("shows the overlay after the delay when disconnected", () => {
    render(<NoConnectionOverlay />);
    // Before delay, overlay not visible
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    // Advance past the 5s delay
    act(() => {
      vi.advanceTimersByTime(5100);
    });
    expect(screen.getByRole("alertdialog")).toBeInTheDocument();
    expect(screen.getByText("OpenAlgo Disconnected")).toBeInTheDocument();
  });

  it("has a Settings button in the overlay", () => {
    render(<NoConnectionOverlay />);
    act(() => {
      vi.advanceTimersByTime(5100);
    });
    expect(screen.getByRole("button", { name: /settings/i })).toBeInTheDocument();
  });
});
