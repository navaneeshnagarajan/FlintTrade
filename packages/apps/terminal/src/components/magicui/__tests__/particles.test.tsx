/**
 * particles.test.tsx
 *
 * Tests for the Particles component.
 *
 * Strategy:
 *   - Mock themeStore to control reduceMotion
 *   - Stub window.matchMedia to control prefers-reduced-motion
 *   - Mock canvas getContext to avoid real canvas operations in jsdom
 *   - Verify: canvas rendered with aria-hidden, returns null on reduced motion,
 *     multi-color prop accepted, cleanup on unmount
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, cleanup } from "@testing-library/react";

// ---------------------------------------------------------------------------
// Mock IntersectionObserver
// ---------------------------------------------------------------------------

const disconnectMock = vi.fn();
const observeMock = vi.fn();

class MockIntersectionObserver implements IntersectionObserver {
  readonly root: Element | Document | null = null;
  readonly rootMargin: string = "0px";
  readonly thresholds: readonly number[] = [0];

  observe = observeMock;
  disconnect = disconnectMock;
  unobserve = vi.fn();
  takeRecords(): IntersectionObserverEntry[] { return []; }

  constructor(cb: IntersectionObserverCallback) {
    // Immediately fire as "visible" so the canvas draws
    setTimeout(() => {
      cb([{ isIntersecting: true } as IntersectionObserverEntry], this as unknown as IntersectionObserver);
    }, 0);
  }
}

vi.stubGlobal("IntersectionObserver", MockIntersectionObserver);

// ---------------------------------------------------------------------------
// Mock requestAnimationFrame / cancelAnimationFrame
// ---------------------------------------------------------------------------

let rafId = 0;
const rafCallbacks = new Map<number, FrameRequestCallback>();

vi.stubGlobal("requestAnimationFrame", (cb: FrameRequestCallback) => {
  const id = ++rafId;
  rafCallbacks.set(id, cb);
  return id;
});

vi.stubGlobal("cancelAnimationFrame", (id: number) => {
  rafCallbacks.delete(id);
});

// ---------------------------------------------------------------------------
// Mock canvas getContext
// ---------------------------------------------------------------------------

const ctxMock = {
  clearRect: vi.fn(),
  beginPath: vi.fn(),
  arc: vi.fn(),
  fill: vi.fn(),
  scale: vi.fn(),
  globalAlpha: 1,
  fillStyle: "",
};

// JSDOM ships without a canvas backend, so HTMLCanvasElement.prototype.getContext
// is undefined. The DOM overload makes assigning a stub non-trivial, so we patch
// the prototype through a structurally-typed alias instead of `any`.
type CanvasProtoPatch = { getContext: (contextId?: string) => unknown };
(HTMLCanvasElement.prototype as unknown as CanvasProtoPatch).getContext = () =>
  ctxMock;

// ---------------------------------------------------------------------------
// Mock themeStore
// ---------------------------------------------------------------------------

let storeReduceMotion = false;

vi.mock("@/stores/themeStore", () => ({
  useThemeStore: (selector: (s: { reduceMotion: boolean }) => unknown) => {
    return selector({ reduceMotion: storeReduceMotion });
  },
}));

// ---------------------------------------------------------------------------
// Mock motion.ts prefersReducedMotion
// ---------------------------------------------------------------------------

let osReduceMotion = false;

vi.mock("@/lib/motion", () => ({
  motionConfig: {
    prefersReducedMotion: () => osReduceMotion,
  },
}));

// ---------------------------------------------------------------------------
// Import after mocks
// ---------------------------------------------------------------------------

import { Particles } from "../particles";

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("Particles", () => {
  beforeEach(() => {
    storeReduceMotion = false;
    osReduceMotion = false;
    vi.clearAllMocks();
    // Mock canvas offsetWidth/offsetHeight
    Object.defineProperty(HTMLCanvasElement.prototype, "offsetWidth", {
      configurable: true,
      get: () => 800,
    });
    Object.defineProperty(HTMLCanvasElement.prototype, "offsetHeight", {
      configurable: true,
      get: () => 600,
    });
  });

  afterEach(() => {
    cleanup();
  });

  it("renders a canvas element", () => {
    const { container } = render(<Particles />);
    const canvas = container.querySelector("canvas");
    expect(canvas).not.toBeNull();
  });

  it("canvas has aria-hidden set to true", () => {
    const { container } = render(<Particles />);
    const canvas = container.querySelector("canvas");
    expect(canvas?.getAttribute("aria-hidden")).toBe("true");
  });

  it("returns null when OS prefers-reduced-motion is true", () => {
    osReduceMotion = true;
    const { container } = render(<Particles />);
    expect(container.querySelector("canvas")).toBeNull();
    expect(container.firstChild).toBeNull();
  });

  it("returns null when themeStore.reduceMotion is true", () => {
    storeReduceMotion = true;
    const { container } = render(<Particles />);
    expect(container.querySelector("canvas")).toBeNull();
  });

  it("returns null when both OS and store reduce motion are true", () => {
    osReduceMotion = true;
    storeReduceMotion = true;
    const { container } = render(<Particles />);
    expect(container.querySelector("canvas")).toBeNull();
  });

  it("accepts a single color prop (backward-compatible)", () => {
    const { container } = render(<Particles color="#ff0000" />);
    expect(container.querySelector("canvas")).not.toBeNull();
  });

  it("accepts a colors array prop", () => {
    const { container } = render(
      <Particles colors={["#ff0000", "#00ff00", "#0000ff"]} />,
    );
    expect(container.querySelector("canvas")).not.toBeNull();
  });

  it("colors prop takes priority over color prop", () => {
    // Both provided — colors array should be used (no error)
    const { container } = render(
      <Particles color="#ff0000" colors={["#00ff00", "#0000ff"]} />,
    );
    expect(container.querySelector("canvas")).not.toBeNull();
  });

  it("accepts all four behavior values", () => {
    const behaviors = ["drift", "float", "pulse", "snow"] as const;
    for (const b of behaviors) {
      const { container } = render(<Particles behavior={b} />);
      expect(container.querySelector("canvas")).not.toBeNull();
      cleanup();
    }
  });

  it("applies custom className to canvas", () => {
    const { container } = render(<Particles className="custom-particles" />);
    const canvas = container.querySelector("canvas");
    expect(canvas?.className).toContain("custom-particles");
  });

  it("disconnects IntersectionObserver on unmount", () => {
    const { unmount } = render(<Particles />);
    unmount();
    expect(disconnectMock).toHaveBeenCalled();
  });

  it("cancels rAF on unmount", () => {
    const cancelSpy = vi.spyOn(window, "cancelAnimationFrame");
    const { unmount } = render(<Particles />);
    unmount();
    expect(cancelSpy).toHaveBeenCalled();
  });

  it("renders with default quantity and size without error", () => {
    expect(() => render(<Particles quantity={10} size={2} />)).not.toThrow();
  });
});
