/** @vitest-environment jsdom */
import * as React from 'react';
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, expect, it, vi } from 'vitest';
import { IntroHandoff } from './intro-handoff';
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });
it('waits for the actual finite signature, ignores continuous decoration, and retires only its own boundary', async () => {
  vi.stubGlobal('React', React);
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true);
  let finish!: () => void;
  const finished = new Promise<void>((resolve) => { finish = resolve; });
  const getAnimations = vi.fn(() => [
    { effect: { getComputedTiming: () => ({ iterations: 1 }) }, finished },
    { effect: { getComputedTiming: () => ({ iterations: Infinity }) }, finished: new Promise(() => {}) },
  ]);
  Object.defineProperty(Element.prototype, 'getAnimations', { configurable: true, value: getAnimations });
  vi.stubGlobal('requestAnimationFrame', (fn: FrameRequestCallback) => { fn(0); return 1; });
  vi.stubGlobal('cancelAnimationFrame', vi.fn());
  const container = document.createElement('div'); document.body.append(container);
  const root = createRoot(container);
  try {
    await act(async () => root.render(<IntroHandoff product={<h1>Product workspace</h1>}><section className="hero">Original signature</section></IntroHandoff>));
    const intro = container.querySelector<HTMLElement>('[data-site-intro]')!;
    const product = container.querySelector<HTMLElement>('[data-site-product]')!;
    expect(intro.hidden).toBe(false); expect(product.hidden).toBe(true);
    await act(async () => finish());
    expect(intro.hidden).toBe(true); expect(product.hidden).toBe(false);
    expect(intro.textContent).toBe('Original signature');
  } finally { await act(async () => root.unmount()); container.remove(); delete (Element.prototype as Partial<Element>).getAnimations; }
});
