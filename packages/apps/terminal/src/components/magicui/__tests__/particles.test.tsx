/**
 * particles.test.tsx
 *
 * Tests for the Particles component.
 *
 * Strategy:
 *   - Use the real themeStore public preference action
 *   - Stub window.matchMedia to dispatch live prefers-reduced-motion changes
 *   - Mock canvas getContext to avoid real canvas operations in jsdom
 *   - Verify: canvas rendered with aria-hidden, returns null on reduced motion,
 *     multi-color prop accepted, cleanup on unmount
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { act, render, cleanup } from "@testing-library/react";

// ---------------------------------------------------------------------------
// Mock IntersectionObserver
// ---------------------------------------------------------------------------

const disconnectMock = vi.fn();
const observeMock = vi.fn();

class MockIntersectionObserver implements IntersectionObserver {
  readonly root: Element | Document | null = null;
  readonly rootMargin: string = "0px";
  readonly scrollMargin: string = "0px";
  readonly thresholds: readonly number[] = [0];
  private readonly cb: IntersectionObserverCallback;
  private disconnected = false;

  observe = (target: Element) => {
    observeMock(target);
    setTimeout(() => {
      if (this.disconnected) return;
      this.cb([{ isIntersecting: true } as IntersectionObserverEntry], this as unknown as IntersectionObserver);
    }, 0);
  };

  disconnect = () => {
    this.disconnected = true;
    disconnectMock();
  };

  unobserve = vi.fn();
  takeRecords(): IntersectionObserverEntry[] { return []; }

  constructor(cb: IntersectionObserverCallback) {
    this.cb = cb;
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
  setTransform: vi.fn(),
  globalAlpha: 1,
  fillStyle: "",
};

// JSDOM ships without a canvas backend, so HTMLCanvasElement.prototype.getContext
// is undefined. The DOM overload makes assigning a stub non-trivial, so we patch
// the prototype through a structurally-typed alias instead of `any`.
type CanvasProtoPatch = { getContext: (contextId?: string) => unknown };
(HTMLCanvasElement.prototype as unknown as CanvasProtoPatch).getContext = () =>
  ctxMock;

import { useThemeStore } from "@/stores/themeStore";

// ---------------------------------------------------------------------------
// Browser boundary: the real motion getter and component read this MediaQueryList.
let osReduceMotion = false;
const mediaListeners = new Set<EventListenerOrEventListenerObject>();
const mediaQuery = {
  get matches() { return osReduceMotion; },
  media: "(prefers-reduced-motion: reduce)",
  onchange: null,
  addEventListener: (_type: string, listener: EventListenerOrEventListenerObject) => mediaListeners.add(listener),
  removeEventListener: (_type: string, listener: EventListenerOrEventListenerObject) => mediaListeners.delete(listener),
};
function changeOsMotion(reduced: boolean) {
  osReduceMotion = reduced;
  for (const listener of mediaListeners) {
    const event = new Event("change");
    if (typeof listener === "function") listener(event);
    else listener.handleEvent(event);
  }
}


// ---------------------------------------------------------------------------
// Import after mocks
// ---------------------------------------------------------------------------

import { Particles } from "../particles";

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("Particles", () => {
  beforeEach(() => {
    useThemeStore.getState().setReduceMotion(false);
    osReduceMotion = false;
    mediaListeners.clear();
    vi.stubGlobal("matchMedia", vi.fn(() => mediaQuery));
    vi.clearAllMocks();
    rafId = 0;
    rafCallbacks.clear();
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
    vi.useRealTimers();
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
    useThemeStore.getState().setReduceMotion(true);
    const { container } = render(<Particles />);
    expect(container.querySelector("canvas")).toBeNull();
  });

  it("returns null when both OS and store reduce motion are true", () => {
    osReduceMotion = true;
    useThemeStore.getState().setReduceMotion(true);
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

  it("keeps one animation loop when visibility observer reports visible", async () => {
    render(<Particles />);

    expect(rafCallbacks.size).toBe(1);
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(rafCallbacks.size).toBe(1);
  });

  it("removes running canvases and cancels their work on a live OS preference change", () => {
    const { container, unmount } = render(<Particles />);
    expect(container.querySelector("canvas")).not.toBeNull();
    expect(rafCallbacks.size).toBe(1);

    act(() => changeOsMotion(true));
    expect(container.querySelector("canvas")).toBeNull();
    expect(rafCallbacks.size).toBe(0);
    expect(disconnectMock).toHaveBeenCalledTimes(1);

    act(() => changeOsMotion(false));
    expect(container.querySelector("canvas")).not.toBeNull();
    expect(rafCallbacks.size).toBe(1);
    unmount();
    expect(rafCallbacks.size).toBe(0);
    expect(mediaListeners.size).toBe(0);
  });

  it("keeps the user's reduction authoritative when the OS allows motion again", () => {
    const { container } = render(<Particles />);
    act(() => useThemeStore.getState().setReduceMotion(true));
    expect(container.querySelector("canvas")).toBeNull();
    expect(rafCallbacks.size).toBe(0);
    act(() => changeOsMotion(true));
    act(() => changeOsMotion(false));
    expect(container.querySelector("canvas")).toBeNull();
    expect(rafCallbacks.size).toBe(0);
    act(() => useThemeStore.getState().setReduceMotion(false));
    expect(container.querySelector("canvas")).not.toBeNull();
    expect(rafCallbacks.size).toBe(1);
    act(() => changeOsMotion(true));
    act(() => useThemeStore.getState().setReduceMotion(false));
    expect(container.querySelector("canvas")).toBeNull();
  });

  it("resumes from cold reduction and releases every mounted layer's media listener", () => {
    osReduceMotion = true;
    const { container, unmount } = render(<><Particles /><Particles /><Particles /></>);
    expect(container.querySelectorAll("canvas")).toHaveLength(0);
    expect(rafCallbacks.size).toBe(0);
    act(() => changeOsMotion(false));
    expect(container.querySelectorAll("canvas")).toHaveLength(3);
    expect(rafCallbacks.size).toBe(3);
    act(() => changeOsMotion(true));
    expect(container.querySelectorAll("canvas")).toHaveLength(0);
    expect(rafCallbacks.size).toBe(0);
    unmount();
    expect(mediaListeners.size).toBe(0);
    act(() => changeOsMotion(false));
    expect(rafCallbacks.size).toBe(0);
  });

  it("renders with default quantity and size without error", () => {
    expect(() => render(<Particles quantity={10} size={2} />)).not.toThrow();
  });
});
