/**
 * InlineHint.test.tsx
 *
 * Tests for the InlineHint component.
 * Verifies rendering, hint visibility based on prefs, tooltip display, and
 * dismiss persistence to localStorage.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import "@testing-library/jest-dom";
import { InlineHint } from "../InlineHint";

// ---------------------------------------------------------------------------
// Mock framer-motion — avoids JSDOM animation issues
// ---------------------------------------------------------------------------
vi.mock("framer-motion", () => ({
  motion: {
    div: ({
      children,
      variants: _variants,
      initial: _initial,
      animate: _animate,
      exit: _exit,
      ...props
    }: React.HTMLAttributes<HTMLDivElement> & Record<string, unknown>) => (
      <div {...props}>{children}</div>
    ),
  },
  AnimatePresence: ({ children }: { children: React.ReactNode }) => (
    <>{children}</>
  ),
}));

// ---------------------------------------------------------------------------
// Mock useHelpPrefs — controllable per test
// ---------------------------------------------------------------------------
const mockHelpPrefs = {
  inlineHints: true,
  spotlightTours: true,
  aiTutor: true,
};

vi.mock("@/hooks/useHelpPrefs", () => ({
  useHelpPrefs: () => mockHelpPrefs,
}));

// ---------------------------------------------------------------------------
// Setup
// ---------------------------------------------------------------------------
beforeEach(() => {
  localStorage.clear();
  mockHelpPrefs.inlineHints = true;
});

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("InlineHint", () => {
  it("renders children and '?' icon when hints enabled", () => {
    render(
      <InlineHint text="This is stop-loss price" featureId="stoploss">
        <span data-testid="label">Stop Loss</span>
      </InlineHint>,
    );

    // Children are present
    expect(screen.getByTestId("label")).toBeInTheDocument();
    expect(screen.getByTestId("label")).toHaveTextContent("Stop Loss");

    // "?" icon button is present
    expect(screen.getByRole("button", { name: /show hint/i })).toBeInTheDocument();
  });

  it("hides '?' icon when hints disabled", () => {
    mockHelpPrefs.inlineHints = false;

    render(
      <InlineHint text="This is stop-loss price" featureId="stoploss">
        <span data-testid="label">Stop Loss</span>
      </InlineHint>,
    );

    // Children are still rendered
    expect(screen.getByTestId("label")).toBeInTheDocument();

    // "?" icon is NOT rendered
    expect(screen.queryByRole("button", { name: /show hint/i })).not.toBeInTheDocument();
  });

  it("shows tooltip text on click", () => {
    render(
      <InlineHint text="Set your maximum acceptable loss" featureId="stoploss">
        <span>Stop Loss</span>
      </InlineHint>,
    );

    // Click the "?" icon to open popover
    const hintButton = screen.getByRole("button", { name: /show hint/i });
    fireEvent.click(hintButton);

    // Tooltip text should now be visible
    expect(screen.getByText("Set your maximum acceptable loss")).toBeInTheDocument();
  });

  it("dismissing stores to localStorage", () => {
    render(
      <InlineHint text="Some explanation" featureId="target-price">
        <span>Target</span>
      </InlineHint>,
    );

    // Open the popover
    const hintButton = screen.getByRole("button", { name: /show hint/i });
    fireEvent.click(hintButton);

    // Find and click the dismiss button
    const dismissButton = screen.getByRole("button", { name: /dismiss hint/i });
    fireEvent.click(dismissButton);

    // localStorage should have the dismissed key
    expect(localStorage.getItem("ft-hint-dismissed-target-price")).toBe("true");

    // The "?" icon should no longer be in the DOM (dismissed)
    expect(screen.queryByRole("button", { name: /show hint/i })).not.toBeInTheDocument();
  });
});
