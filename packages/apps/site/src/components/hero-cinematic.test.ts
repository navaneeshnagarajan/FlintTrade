/** @vitest-environment jsdom */

import { act, createElement } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('next-themes', () => ({
  useTheme: () => ({ resolvedTheme: 'dark' }),
}));

import { HeroCinematic } from './hero-cinematic';

describe('HeroCinematic coexistence with the progressive WebGL layer', () => {
  let container: HTMLDivElement;
  let root: Root;
  let cancelled: number[];
  let nextFrameId: number;

  beforeEach(() => {
    (globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
    cancelled = [];
    nextFrameId = 0;

    vi.stubGlobal('requestAnimationFrame', vi.fn(() => ++nextFrameId));
    vi.stubGlobal('cancelAnimationFrame', vi.fn((id: number) => cancelled.push(id)));
    vi.stubGlobal('IntersectionObserver', class {
      constructor(private readonly callback: IntersectionObserverCallback) {}
      observe(target: Element) {
        this.callback([{ isIntersecting: true, target } as IntersectionObserverEntry], this as unknown as IntersectionObserver);
      }
      disconnect() {}
      unobserve() {}
      takeRecords() { return []; }
      root = null;
      rootMargin = '0px';
      thresholds = [0];
    });
    window.matchMedia = vi.fn(() => ({
      matches: false,
      media: '(prefers-reduced-motion: reduce)',
      onchange: null,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      addListener: vi.fn(),
      removeListener: vi.fn(),
      dispatchEvent: vi.fn(),
    }));
    vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue({
      setTransform: vi.fn(),
      clearRect: vi.fn(),
      beginPath: vi.fn(),
      arc: vi.fn(),
      fill: vi.fn(),
      globalAlpha: 1,
      fillStyle: '',
    } as unknown as CanvasRenderingContext2D);

    container = document.createElement('div');
    document.body.append(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it('pauses every Canvas2D loop after the first WebGL frame and resumes on fail-open fallback', async () => {
    await act(async () => root.render(createElement(HeroCinematic)));
    const canvases = [...container.querySelectorAll<HTMLCanvasElement>('.site-particles')];
    expect(canvases).toHaveLength(3);
    expect(canvases.every((canvas) => canvas.dataset.animationState === 'running')).toBe(true);

    await act(async () => window.dispatchEvent(new CustomEvent('ft-scroll-world-ready')));
    expect(canvases.every((canvas) => canvas.dataset.animationState === 'paused')).toBe(true);
    expect(cancelled.length).toBeGreaterThanOrEqual(3);

    await act(async () => window.dispatchEvent(new CustomEvent('ft-scroll-world-fallback')));
    expect(canvases.every((canvas) => canvas.dataset.animationState === 'running')).toBe(true);
  });
});
