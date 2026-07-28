/**
 * NoConnectionOverlay.test.tsx — Renders connection warning with Settings button.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, act } from "@testing-library/react";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

let connectionStatus = "disconnected";
let tradingMode = "live";

vi.mock("@/stores/connectionStore", () => ({
  useConnectionStore: (selector: (s: { status: string }) => unknown) =>
    selector({ status: connectionStatus }),
}));

vi.mock("@/stores/modeStore", () => ({
  useModeStore: (selector: (s: { mode: string }) => unknown) =>
    selector({ mode: tradingMode }),
}));

const mockNavigate = vi.fn();
vi.mock("react-router", () => ({
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
    tradingMode = "live";
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
    expect(screen.getByText("Live Broker Data Disconnected")).toBeInTheDocument();
  });

  it("has a Settings button in the overlay", () => {
    render(<NoConnectionOverlay />);
    act(() => {
      vi.advanceTimersByTime(5100);
    });
    expect(screen.getByRole("button", { name: /settings/i })).toBeInTheDocument();
  });

  it.each(["explore", "practice"])(
    "does not block the %s workspace when broker data is unavailable",
    (mode) => {
      tradingMode = mode;
      render(<NoConnectionOverlay />);

      act(() => {
        vi.advanceTimersByTime(5100);
      });

      expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    },
  );
});
