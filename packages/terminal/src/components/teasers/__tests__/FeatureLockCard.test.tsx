/**
 * FeatureLockCard.test.tsx
 *
 * Tests for the FeatureLockCard fully-locked feature card.
 * Verifies feature name/description rendering, RoadmapBadge presence,
 * and snapshot stability.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";
import { FeatureLockCard } from "../FeatureLockCard";

// ---------------------------------------------------------------------------
// Mock framer-motion
// ---------------------------------------------------------------------------
vi.mock("framer-motion", () => ({
  motion: {
    div: ({
      children,
      ...props
    }: React.HTMLAttributes<HTMLDivElement> & {
      whileHover?: unknown;
      animate?: unknown;
      initial?: unknown;
    }) => {
      const { whileHover: _wh, animate: _a, initial: _i, ...rest } = props as Record<string, unknown>;
      void _wh; void _a; void _i;
      return <div {...(rest as React.HTMLAttributes<HTMLDivElement>)}>{children}</div>;
    },
  },
  AnimatePresence: ({ children }: { children: React.ReactNode }) => (
    <>{children}</>
  ),
}));

// ---------------------------------------------------------------------------
// Silence matchMedia
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
});

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("FeatureLockCard", () => {
  it("renders feature name and description", () => {
    render(
      <FeatureLockCard
        config={{ featureName: "Portfolio Greeks", status: "in_dev", version: "v0.4.0" }}
        description="Real-time delta, gamma, theta and vega across your entire portfolio."
      />,
    );

    // Feature name appears as a heading
    expect(
      screen.getByRole("heading", { name: /Portfolio Greeks/i }),
    ).toBeInTheDocument();

    // Description text is present
    expect(
      screen.getByText(/delta, gamma, theta and vega/i),
    ).toBeInTheDocument();
  });

  it("shows RoadmapBadge with the correct status", () => {
    render(
      <FeatureLockCard
        config={{ featureName: "Multi-Account Mirror", status: "testing" }}
        description="Mirror trades across accounts with configurable lag."
      />,
    );

    // RoadmapBadge renders a group with aria-label containing current stage
    expect(
      screen.getByRole("group", {
        name: /Feature roadmap — current stage: Testing/i,
      }),
    ).toBeInTheDocument();
  });

  it("matches snapshot", () => {
    const { container } = render(
      <FeatureLockCard
        config={{
          featureName: "Backtest Engine",
          status: "preview",
          version: "v0.3.0",
          notifyChannel: "telegram",
        }}
        description="Tick-level backtesting powered by the Rust engine."
      />,
    );

    expect(container).toMatchSnapshot();
  });
});
