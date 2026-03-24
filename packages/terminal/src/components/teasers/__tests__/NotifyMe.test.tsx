/**
 * NotifyMe.test.tsx
 *
 * Tests for the NotifyMe CTA component.
 * Verifies initial state, localStorage persistence on click,
 * post-click "Subscribed" UI, and snapshot for subscribed state.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import "@testing-library/jest-dom";
import { NotifyMe } from "../NotifyMe";
import { NOTIFY_PREFS_KEY } from "../types";

// ---------------------------------------------------------------------------
// Mock framer-motion — AnimatePresence mode="wait" causes issues in JSDOM
// ---------------------------------------------------------------------------
vi.mock("framer-motion", () => ({
  motion: {
    div: ({
      children,
      ...props
    }: React.HTMLAttributes<HTMLDivElement> & { exit?: unknown; animate?: unknown; initial?: unknown }) => {
      // Strip framer-motion-only props to avoid React unknown-prop warnings
      const { exit: _exit, animate: _animate, initial: _initial, ...rest } = props as Record<string, unknown>;
      void _exit; void _animate; void _initial;
      return <div {...(rest as React.HTMLAttributes<HTMLDivElement>)}>{children}</div>;
    },
  },
  AnimatePresence: ({ children }: { children: React.ReactNode }) => (
    <>{children}</>
  ),
}));

// ---------------------------------------------------------------------------
// Reset localStorage before each test
// ---------------------------------------------------------------------------
beforeEach(() => {
  localStorage.clear();
  vi.restoreAllMocks();
});

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("NotifyMe", () => {
  it("shows Notify me button initially", () => {
    render(<NotifyMe config={{ featureName: "Flow Builder" }} />);

    // ShimmerButton renders a <button> whose accessible name comes from text content
    expect(
      screen.getByRole("button", { name: /notify me when live/i }),
    ).toBeInTheDocument();

    // "Subscribed" confirmation should not be visible
    expect(screen.queryByText(/subscribed/i)).not.toBeInTheDocument();
  });

  it("clicking stores the notification preference in localStorage", () => {
    const setItemSpy = vi.spyOn(Storage.prototype, "setItem");

    render(<NotifyMe config={{ featureName: "Strategy Lab", notifyChannel: "telegram" }} />);

    const button = screen.getByRole("button", {
      name: /notify me when live/i,
    });
    fireEvent.click(button);

    // setItem must have been called with the correct key
    expect(setItemSpy).toHaveBeenCalledWith(
      NOTIFY_PREFS_KEY,
      expect.any(String),
    );

    // Verify stored value contains correct featureName and channel
    const storedRaw = localStorage.getItem(NOTIFY_PREFS_KEY);
    expect(storedRaw).not.toBeNull();
    const stored = JSON.parse(storedRaw!) as Array<{ featureName: string; channel: string }>;
    expect(stored).toHaveLength(1);
    expect(stored[0].featureName).toBe("Strategy Lab");
    expect(stored[0].channel).toBe("telegram");
  });

  it("shows Subscribed after clicking the notify button", () => {
    render(<NotifyMe config={{ featureName: "AI Signals" }} />);

    const button = screen.getByRole("button", {
      name: /notify me when live/i,
    });
    fireEvent.click(button);

    // Subscribed confirmation text must appear
    expect(screen.getByText(/subscribed/i)).toBeInTheDocument();

    // Original CTA button is gone
    expect(
      screen.queryByRole("button", { name: /notify me when live/i }),
    ).not.toBeInTheDocument();
  });

  it("matches snapshot for subscribed state", () => {
    // Pre-populate localStorage so the component mounts already subscribed
    const pref = { featureName: "Portfolio Greeks", channel: "telegram", timestamp: 1700000000000 };
    localStorage.setItem(NOTIFY_PREFS_KEY, JSON.stringify([pref]));

    const { container } = render(
      <NotifyMe config={{ featureName: "Portfolio Greeks" }} />,
    );

    expect(container).toMatchSnapshot();
  });
});
