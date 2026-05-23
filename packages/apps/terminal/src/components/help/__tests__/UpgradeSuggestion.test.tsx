/**
 * UpgradeSuggestion.test.tsx
 *
 * Tests for the UpgradeSuggestionHost component.
 *
 * 1. Renders suggestion text and all three buttons
 * 2. "Upgrade" calls setRouteOverride with the correct arguments
 * 3. "Don't ask again" calls dismissSuggestion with the correct key
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, act } from "@testing-library/react";
import "@testing-library/jest-dom";
import { UpgradeSuggestionHost } from "../UpgradeSuggestion";
import type { UpgradeSuggestion } from "@/types/skill";

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
// Mock skillStore with controllable state
// ---------------------------------------------------------------------------

const mockSetRouteOverride  = vi.fn();
const mockDismissSuggestion = vi.fn();
let mockSuggestions: UpgradeSuggestion[] = [];

vi.mock("@/stores/skillStore", () => ({
  useSkillStore: (selector: (state: Record<string, unknown>) => unknown) => {
    const state = {
      setRouteOverride:  mockSetRouteOverride,
      dismissSuggestion: mockDismissSuggestion,
      getSuggestions:    () => mockSuggestions,
    };
    return selector(state);
  },
}));

// ---------------------------------------------------------------------------
// Mock @/lib/motion to avoid matchMedia in JSDOM
// ---------------------------------------------------------------------------
vi.mock("@/lib/motion", () => ({
  motionConfig: {
    prefersReducedMotion: () => true,
  },
  DURATION: { fast: 0.1, normal: 0.2, slow: 0.3 },
  EASE_ENTER: "easeIn",
  EASE_EXIT: "easeOut",
}));

// ---------------------------------------------------------------------------
// Sample suggestion
// ---------------------------------------------------------------------------

const SAMPLE_SUGGESTION: UpgradeSuggestion = {
  domain: "trade",
  fromLevel: "beginner",
  toLevel: "intermediate",
  reason: "You've placed 20 trades over 7 days. Ready for more tools?",
  timestamp: 1000,
};

// ---------------------------------------------------------------------------
// Setup
// ---------------------------------------------------------------------------

beforeEach(() => {
  vi.clearAllMocks();
  mockSuggestions = [];
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
});

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("UpgradeSuggestionHost", () => {
  it("renders suggestion text and all three action buttons", async () => {
    mockSuggestions = [SAMPLE_SUGGESTION];

    render(<UpgradeSuggestionHost />);

    // Advance past the 3 s initial delay
    await act(async () => { vi.advanceTimersByTime(3500); });

    // Suggestion text and heading should be visible
    expect(
      screen.getByText(/Ready for more tools\?/i),
    ).toBeInTheDocument();

    expect(screen.getByRole("button", { name: /upgrade/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /not now/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /don't ask again/i })).toBeInTheDocument();
  });

  it("Upgrade button calls setRouteOverride with the correct domain and level", async () => {
    mockSuggestions = [SAMPLE_SUGGESTION];

    render(<UpgradeSuggestionHost />);

    await act(async () => { vi.advanceTimersByTime(3500); });

    fireEvent.click(screen.getByRole("button", { name: /upgrade/i }));

    expect(mockSetRouteOverride).toHaveBeenCalledOnce();
    expect(mockSetRouteOverride).toHaveBeenCalledWith("trade", "intermediate");
  });

  it("Don't ask again calls dismissSuggestion with domain:level key", async () => {
    mockSuggestions = [SAMPLE_SUGGESTION];

    render(<UpgradeSuggestionHost />);

    await act(async () => { vi.advanceTimersByTime(3500); });

    fireEvent.click(screen.getByRole("button", { name: /don't ask again/i }));

    expect(mockDismissSuggestion).toHaveBeenCalledOnce();
    expect(mockDismissSuggestion).toHaveBeenCalledWith("trade:intermediate");
  });
});
