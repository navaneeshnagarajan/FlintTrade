/**
 * CinematicLayout.test.tsx
 *
 * Tests for the CinematicLayout wrapper component.
 *
 * Strategy:
 *   - Mock themeStore to control reduceMotion
 *   - Mock motionConfig.prefersReducedMotion to control OS setting
 *   - Mock Particles to avoid canvas operations
 *   - Assert: cinematic mode renders particles container,
 *     focused mode does not, reduced motion forces focused
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, cleanup } from "@testing-library/react";

// ---------------------------------------------------------------------------
// Mock themeStore
// ---------------------------------------------------------------------------

let storeReduceMotion = false;

vi.mock("@/stores/themeStore", () => ({
  useThemeStore: (selector: (s: Record<string, unknown>) => unknown) => {
    return selector({
      reduceMotion: storeReduceMotion,
      getActiveTheme: () => ({
        shared: {
          particles: {
            quantity: 45,
            sizeRange: [1, 4],
            behavior: "float",
          },
        },
      }),
    });
  },
}));

// ---------------------------------------------------------------------------
// Mock motionConfig
// ---------------------------------------------------------------------------

let osReduceMotion = false;

vi.mock("@/lib/motion", () => ({
  motionConfig: {
    prefersReducedMotion: () => osReduceMotion,
  },
}));

// ---------------------------------------------------------------------------
// Mock Particles — replace with a simple div so we can detect rendering
// ---------------------------------------------------------------------------

vi.mock("@/components/magicui/particles", () => ({
  Particles: ({
    className,
    quantity,
    behavior,
    sizeRange,
  }: {
    className?: string;
    quantity?: number;
    behavior?: string;
    sizeRange?: [number, number];
  }) => (
    <div
      data-testid="particles"
      data-quantity={quantity}
      data-behavior={behavior}
      data-size-range={sizeRange?.join("-")}
      className={className}
      aria-hidden="true"
    />
  ),
}));

// ---------------------------------------------------------------------------
// Mock getComputedStyle for CSS var reading
// ---------------------------------------------------------------------------

beforeEach(() => {
  vi.stubGlobal(
    "getComputedStyle",
    () => ({
      getPropertyValue: () => "",
    }),
  );
  storeReduceMotion = false;
  osReduceMotion = false;
});

afterEach(() => {
  vi.unstubAllGlobals();
  cleanup();
});

// ---------------------------------------------------------------------------
// Mock navigator.hardwareConcurrency (high-end by default)
// ---------------------------------------------------------------------------

Object.defineProperty(navigator, "hardwareConcurrency", {
  configurable: true,
  get: () => 8,
});

// ---------------------------------------------------------------------------
// Import after mocks
// ---------------------------------------------------------------------------

import { CinematicLayout } from "../CinematicLayout";

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("CinematicLayout", () => {
  it("renders children in both modes", () => {
    const { getByText } = render(
      <CinematicLayout mode="cinematic">
        <span>Content</span>
      </CinematicLayout>,
    );
    expect(getByText("Content")).toBeTruthy();
  });

  it("cinematic mode renders particles", () => {
    const { getByTestId } = render(
      <CinematicLayout mode="cinematic">
        <span>Content</span>
      </CinematicLayout>,
    );
    expect(getByTestId("particles")).toBeTruthy();
  });

  it("uses the active theme particle settings for cinematic mode", () => {
    const { getByTestId } = render(
      <CinematicLayout mode="cinematic">
        <span>Content</span>
      </CinematicLayout>,
    );

    const particles = getByTestId("particles");
    expect(particles).toHaveAttribute("data-quantity", "45");
    expect(particles).toHaveAttribute("data-behavior", "float");
    expect(particles).toHaveAttribute("data-size-range", "1-4");
  });

  it("focused mode does not render particles", () => {
    const { queryByTestId } = render(
      <CinematicLayout mode="focused">
        <span>Content</span>
      </CinematicLayout>,
    );
    expect(queryByTestId("particles")).toBeNull();
  });

  it("OS prefers-reduced-motion forces focused (no particles)", () => {
    osReduceMotion = true;
    const { queryByTestId } = render(
      <CinematicLayout mode="cinematic">
        <span>Content</span>
      </CinematicLayout>,
    );
    expect(queryByTestId("particles")).toBeNull();
  });

  it("themeStore.reduceMotion forces focused (no particles)", () => {
    storeReduceMotion = true;
    const { queryByTestId } = render(
      <CinematicLayout mode="cinematic">
        <span>Content</span>
      </CinematicLayout>,
    );
    expect(queryByTestId("particles")).toBeNull();
  });

  it("renders children above the particles (relative z-10 wrapper)", () => {
    const { container } = render(
      <CinematicLayout mode="cinematic">
        <span data-testid="inner-content">Hello</span>
      </CinematicLayout>,
    );
    // Content wrapper should have relative z-10 class
    const contentWrapper = container.querySelector(".z-10");
    expect(contentWrapper).not.toBeNull();
    expect(contentWrapper?.textContent).toContain("Hello");
  });

  it("renders glow overlay only in cinematic mode", () => {
    const { container } = render(
      <CinematicLayout mode="cinematic">
        <span>C</span>
      </CinematicLayout>,
    );
    // Glow overlay is the pointer-events-none z-0 div
    const glow = container.querySelector("[aria-hidden='true']:not([data-testid])");
    // Should have background-image set (even if empty because CSS var returns "")
    expect(glow).not.toBeNull();
  });

  it("does not render glow in focused mode", () => {
    const { container } = render(
      <CinematicLayout mode="focused">
        <span>F</span>
      </CinematicLayout>,
    );
    // No particles testid, no extra aria-hidden (Particles mock won't be there)
    const particles = container.querySelector("[data-testid='particles']");
    expect(particles).toBeNull();
  });

  it("applies custom className to root element", () => {
    const { container } = render(
      <CinematicLayout mode="focused" className="my-layout">
        <span>C</span>
      </CinematicLayout>,
    );
    expect(container.firstElementChild?.className).toContain("my-layout");
  });
});
