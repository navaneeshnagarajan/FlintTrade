/**
 * SpotlightTour.test.tsx
 *
 * Tests for the SpotlightTour component.
 * Verifies rendering logic, completion persistence, step navigation,
 * and localStorage-based tour completion tracking.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import "@testing-library/jest-dom";
import { SpotlightTour } from "../SpotlightTour";
import type { TourStep } from "@/lib/tourDefinitions";

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
    rect: (props: Record<string, unknown>) => <rect {...props} />,
  },
  AnimatePresence: ({
    children,
  }: {
    children: React.ReactNode;
    mode?: string;
  }) => <>{children}</>,
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
// Silence matchMedia — jsdom does not implement it
// ---------------------------------------------------------------------------
beforeEach(() => {
  Object.defineProperty(window, "matchMedia", {
    writable: true,
    value: vi.fn().mockImplementation(() => ({
      matches: false,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    })),
  });
  localStorage.clear();
  mockHelpPrefs.spotlightTours = true;
});

// ---------------------------------------------------------------------------
// Test data
// ---------------------------------------------------------------------------

const testSteps: TourStep[] = [
  {
    target: "watchlist",
    title: "Your Watchlist",
    description: "Track your favorite stocks here.",
    position: "right",
  },
  {
    target: "chart",
    title: "Price Chart",
    description: "See price movements over time.",
    position: "bottom",
  },
  {
    target: "orderpad",
    title: "Place Orders",
    description: "Buy or sell from here.",
    position: "left",
  },
];

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("SpotlightTour", () => {
  it("renders when tour not completed and prefs enabled", () => {
    render(
      <SpotlightTour tourId="test-tour" steps={testSteps} />,
    );

    // The spotlight tour dialog should be present
    expect(screen.getByTestId("spotlight-tour")).toBeInTheDocument();
    expect(
      screen.getByRole("dialog", { name: /guided tour/i }),
    ).toBeInTheDocument();

    // First step content should be visible
    expect(screen.getByText("Your Watchlist")).toBeInTheDocument();
    expect(screen.getByText("Track your favorite stocks here.")).toBeInTheDocument();

    // Step counter should show "1 of 3"
    expect(screen.getByText("1 of 3")).toBeInTheDocument();
  });

  it("does not render when tour already completed", () => {
    // Pre-set completion in localStorage
    localStorage.setItem("ft-tour-completed-test-tour", "true");

    render(
      <SpotlightTour tourId="test-tour" steps={testSteps} />,
    );

    // Tour should NOT be in the DOM
    expect(screen.queryByTestId("spotlight-tour")).not.toBeInTheDocument();
  });

  it("advances steps on Next click", () => {
    render(
      <SpotlightTour tourId="test-tour" steps={testSteps} />,
    );

    // Step 1
    expect(screen.getByText("Your Watchlist")).toBeInTheDocument();
    expect(screen.getByText("1 of 3")).toBeInTheDocument();

    // Click Next
    const nextButton = screen.getByTestId("tour-next");
    fireEvent.click(nextButton);

    // Step 2
    expect(screen.getByText("Price Chart")).toBeInTheDocument();
    expect(screen.getByText("2 of 3")).toBeInTheDocument();

    // Click Next again
    fireEvent.click(screen.getByTestId("tour-next"));

    // Step 3 (last step)
    expect(screen.getByText("Place Orders")).toBeInTheDocument();
    expect(screen.getByText("3 of 3")).toBeInTheDocument();

    // Next button should now say "Finish"
    expect(screen.getByTestId("tour-next")).toHaveTextContent("Finish");
  });

  it("stores completion in localStorage on finish", () => {
    const handleComplete = vi.fn();

    render(
      <SpotlightTour
        tourId="test-tour"
        steps={testSteps}
        onComplete={handleComplete}
      />,
    );

    // Navigate through all steps
    fireEvent.click(screen.getByTestId("tour-next")); // step 1 -> 2
    fireEvent.click(screen.getByTestId("tour-next")); // step 2 -> 3
    fireEvent.click(screen.getByTestId("tour-next")); // step 3 -> finish

    // localStorage should have the completion key
    expect(localStorage.getItem("ft-tour-completed-test-tour")).toBe("true");

    // onComplete callback should have been called
    expect(handleComplete).toHaveBeenCalledOnce();
  });
});
