/**
 * useNarrowLayout — container-width switch for phone-width books.
 *
 * Positions and Holdings clip P&L at ~390px when they stay on the wide
 * table. This hook is the single measurement used by both surfaces.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { act, render, screen } from "@testing-library/react";
import { useNarrowLayout } from "../useNarrowLayout";

function Harness({ maxWidth }: { maxWidth?: number }) {
  const { isNarrow, containerRef } = useNarrowLayout<HTMLDivElement>(maxWidth);
  return (
    <div ref={containerRef} data-testid="narrow-target" data-narrow={isNarrow ? "true" : "false"}>
      box
    </div>
  );
}

describe("useNarrowLayout", () => {
  let resizeCallback: ResizeObserverCallback | null = null;

  beforeEach(() => {
    resizeCallback = null;
    vi.stubGlobal(
      "ResizeObserver",
      class ResizeObserver {
        constructor(callback: ResizeObserverCallback) {
          resizeCallback = callback;
        }
        observe = vi.fn();
        disconnect = vi.fn();
        unobserve = vi.fn();
      },
    );
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("stays wide until a positive width is measured", () => {
    render(<Harness />);
    expect(screen.getByTestId("narrow-target")).toHaveAttribute("data-narrow", "false");
  });

  it("becomes narrow at a 390px phone-width container", () => {
    render(<Harness />);

    act(() => {
      resizeCallback?.(
        [{ contentRect: { width: 390, height: 700 } } as ResizeObserverEntry],
        {} as ResizeObserver,
      );
    });

    expect(screen.getByTestId("narrow-target")).toHaveAttribute("data-narrow", "true");
  });

  it("stays wide at an 800px desktop container", () => {
    render(<Harness />);

    act(() => {
      resizeCallback?.(
        [{ contentRect: { width: 800, height: 700 } } as ResizeObserverEntry],
        {} as ResizeObserver,
      );
    });

    expect(screen.getByTestId("narrow-target")).toHaveAttribute("data-narrow", "false");
  });

  it("ignores a zero-width measurement so jsdom 0×0 rects do not flip the layout", () => {
    render(<Harness />);

    act(() => {
      resizeCallback?.(
        [{ contentRect: { width: 0, height: 0 } } as ResizeObserverEntry],
        {} as ResizeObserver,
      );
    });

    expect(screen.getByTestId("narrow-target")).toHaveAttribute("data-narrow", "false");
  });
});
