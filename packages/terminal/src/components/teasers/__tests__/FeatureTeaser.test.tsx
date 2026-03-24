/**
 * FeatureTeaser.test.tsx
 *
 * Tests for the FeatureTeaser wrapper component.
 * Verifies overlay rendering, live passthrough, banner presence, and opacity dimming.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";
import { FeatureTeaser } from "../FeatureTeaser";

// ---------------------------------------------------------------------------
// Mock framer-motion — avoids JSDOM animation issues and layoutId warnings
// ---------------------------------------------------------------------------
vi.mock("framer-motion", () => ({
  motion: {
    div: ({ children, ...props }: React.HTMLAttributes<HTMLDivElement>) => (
      <div {...props}>{children}</div>
    ),
  },
  AnimatePresence: ({ children }: { children: React.ReactNode }) => (
    <>{children}</>
  ),
}));

// ---------------------------------------------------------------------------
// Mock themeStore — PreviewBanner reads glass.enabled
// ---------------------------------------------------------------------------
vi.mock("@/stores/themeStore", () => ({
  useThemeStore: () => false,
}));

// ---------------------------------------------------------------------------
// Mock zustand/react/shallow — used inside PreviewBanner
// ---------------------------------------------------------------------------
vi.mock("zustand/react/shallow", () => ({
  useShallow: (selector: (s: unknown) => unknown) => selector,
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
});

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("FeatureTeaser", () => {
  it("renders children with overlay when status is preview", () => {
    render(
      <FeatureTeaser featureName="AI Advisor" status="preview">
        <div data-testid="widget-content">Chart Widget</div>
      </FeatureTeaser>,
    );

    // Children are present
    expect(screen.getByTestId("widget-content")).toBeInTheDocument();

    // Section aria-label confirms teaser overlay is active
    expect(
      screen.getByRole("region", { name: /AI Advisor.*preview/i }),
    ).toBeInTheDocument();
  });

  it("renders children without overlay when status is live", () => {
    render(
      <FeatureTeaser featureName="AI Advisor" status="live">
        <div data-testid="live-content">Live Widget</div>
      </FeatureTeaser>,
    );

    expect(screen.getByTestId("live-content")).toBeInTheDocument();

    // No section region — live just renders children
    expect(
      screen.queryByRole("region", { name: /AI Advisor/i }),
    ).not.toBeInTheDocument();
  });

  it("shows PreviewBanner with correct feature name", () => {
    render(
      <FeatureTeaser featureName="Flow Builder" status="in_dev">
        <div>content</div>
      </FeatureTeaser>,
    );

    // PreviewBanner renders aria-label with feature name
    expect(
      screen.getByRole("status", { name: /Flow Builder/i }),
    ).toBeInTheDocument();
  });

  it("dims children to opacity 0.6 when not live", () => {
    const { container } = render(
      <FeatureTeaser featureName="Backtest" status="testing">
        <div data-testid="inner">Backtest content</div>
      </FeatureTeaser>,
    );

    // The dimming wrapper is the first child div of the section
    const section = container.querySelector("section");
    expect(section).not.toBeNull();

    const dimmingWrapper = section!.querySelector(
      '[aria-hidden="true"][style*="opacity"]',
    );
    expect(dimmingWrapper).not.toBeNull();
    expect(dimmingWrapper!.getAttribute("style")).toContain("opacity: 0.6");
  });

  it("matches snapshot for preview status", () => {
    const { container } = render(
      <FeatureTeaser featureName="Strategy Lab" status="preview" version="v0.3.0">
        <div>preview widget content</div>
      </FeatureTeaser>,
    );

    expect(container).toMatchSnapshot();
  });
});
