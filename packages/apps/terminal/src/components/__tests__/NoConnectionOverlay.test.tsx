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
let brokerAccounts: Array<{ status: string; source: "gateway" | "native" }> = [];

const brokerMocks = vi.hoisted(() => ({
  useBrokerAccounts: vi.fn(),
}));

vi.mock("@/stores/connectionStore", () => ({
  useConnectionStore: (selector: (s: { status: string }) => unknown) =>
    selector({ status: connectionStatus }),
}));

vi.mock("@/stores/modeStore", () => ({
  useModeStore: (selector: (s: { mode: string }) => unknown) =>
    selector({ mode: tradingMode }),
}));

vi.mock("@/stores/brokerStore", () => ({
  useBrokerStore: (
    selector: (s: {
      accounts: Array<{ status: string; source: "gateway" | "native" }>;
    }) => unknown,
  ) => selector({ accounts: brokerAccounts }),
}));

vi.mock("@/hooks/useBrokerAccounts", () => ({
  useBrokerAccounts: brokerMocks.useBrokerAccounts,
}));

vi.mock("zustand/react/shallow", () => ({
  useShallow: (selector: unknown) => selector,
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
    brokerAccounts = [];
    brokerMocks.useBrokerAccounts.mockClear();
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

  it("cannot be dismissed while Live mode remains disconnected", () => {
    render(<NoConnectionOverlay />);
    act(() => {
      vi.advanceTimersByTime(5100);
    });

    expect(screen.getByRole("alertdialog")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /dismiss/i })).not.toBeInTheDocument();
    expect(screen.queryByText(/continue without live data/i)).not.toBeInTheDocument();
  });

  it("does not block a native-only Live workspace while OpenAlgo is disconnected", () => {
    brokerAccounts = [{ status: "connected", source: "native" }];
    render(<NoConnectionOverlay />);

    act(() => {
      vi.advanceTimersByTime(5100);
    });

    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
  });

  it("uses the requested composite Live state when another native account is connected", () => {
    brokerAccounts = [
      { status: "disconnected", source: "native" },
      { status: "connected", source: "native" },
    ];
    render(<NoConnectionOverlay />);

    act(() => {
      vi.advanceTimersByTime(5100);
    });

    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
  });

  it("still accepts the legacy OpenAlgo-connected path when no account snapshot exists", () => {
    connectionStatus = "connected";
    render(<NoConnectionOverlay />);

    act(() => {
      vi.advanceTimersByTime(5100);
    });

    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
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
