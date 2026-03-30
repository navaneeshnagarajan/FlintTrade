/**
 * ContextTipCard.test.tsx
 *
 * Tests for the ContextTipCard component — verifies rendering, dismiss behavior,
 * and learn-more navigation.
 */

import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import "@testing-library/jest-dom";
import { ContextTipCard } from "../ContextTipCard";

// ---------------------------------------------------------------------------
// Mock framer-motion
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
// Mock react-router-dom
// ---------------------------------------------------------------------------

const mockNavigate = vi.fn();
vi.mock("react-router-dom", () => ({
  useNavigate: () => mockNavigate,
}));

// ---------------------------------------------------------------------------
// Mock skillStore
// ---------------------------------------------------------------------------

const mockState = {
  globalLevel: "beginner" as "beginner" | "intermediate" | "advanced",
  helpPrefs: { inlineHints: true, spotlightTours: true, aiTutor: true },
};

vi.mock("@/stores/skillStore", () => ({
  useSkillStore: (selector: (s: typeof mockState) => unknown) => selector(mockState),
}));

// ---------------------------------------------------------------------------
// localStorage mock
// ---------------------------------------------------------------------------

let storage: Record<string, string> = {};

beforeEach(() => {
  storage = {};
  vi.spyOn(Storage.prototype, "getItem").mockImplementation(
    (key: string) => storage[key] ?? null,
  );
  vi.spyOn(Storage.prototype, "setItem").mockImplementation(
    (key: string, value: string) => {
      storage[key] = value;
    },
  );
  mockState.globalLevel = "beginner";
  mockState.helpPrefs.inlineHints = true;
  mockNavigate.mockClear();
});

afterEach(() => {
  vi.restoreAllMocks();
});

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("ContextTipCard", () => {
  it("renders a tip for a valid trigger", () => {
    render(<ContextTipCard trigger="widget:optionchain" />);
    expect(screen.getByText("What is an Option Chain?")).toBeInTheDocument();
  });

  it("renders nothing for an unknown trigger", () => {
    const { container } = render(<ContextTipCard trigger="widget:nonexistent" />);
    expect(container.textContent).toBe("");
  });

  it("shows difficulty badge", () => {
    render(<ContextTipCard trigger="widget:optionchain" />);
    expect(screen.getByText("beginner")).toBeInTheDocument();
  });

  it("shows Learn More button that navigates to /learn", () => {
    render(<ContextTipCard trigger="widget:optionchain" />);
    const learnMore = screen.getByText("Learn More");
    fireEvent.click(learnMore);
    expect(mockNavigate).toHaveBeenCalledWith("/learn");
  });

  it("shows Got it button that dismisses the tip", () => {
    render(<ContextTipCard trigger="widget:optionchain" />);
    const gotIt = screen.getByText("Got it");
    fireEvent.click(gotIt);

    // After dismiss, the tip should be stored in localStorage
    const stored = JSON.parse(storage["flinttrade:dismissed-tips"] ?? "[]") as string[];
    expect(stored.length).toBeGreaterThan(0);
  });

  it("renders nothing when inlineHints is disabled", () => {
    mockState.helpPrefs.inlineHints = false;
    const { container } = render(<ContextTipCard trigger="widget:optionchain" />);
    expect(container.textContent).toBe("");
  });

  it("renders a tip for widget:chart", () => {
    render(<ContextTipCard trigger="widget:chart" />);
    expect(screen.getByText("Reading Candlestick Charts")).toBeInTheDocument();
  });

  it("renders a tip for widget:greeks", () => {
    render(<ContextTipCard trigger="widget:greeks" />);
    expect(screen.getByText("What are the Greeks?")).toBeInTheDocument();
  });

  it("has a dismiss button with accessible label", () => {
    render(<ContextTipCard trigger="widget:optionchain" />);
    expect(screen.getByLabelText("Dismiss tip")).toBeInTheDocument();
  });
});
