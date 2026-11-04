/** @vitest-environment jsdom */
import * as React from 'react';
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { IntroHandoff } from './intro-handoff';
import { ProductIntroduction } from './product-introduction';
import ExplorePage from '../app/explore/page';
let container: HTMLDivElement;
let root: ReturnType<typeof createRoot>;
let finish: () => void;
let preference: EventTarget;
let getAnimations: ReturnType<typeof vi.fn>;
beforeEach(() => {
  vi.stubGlobal('React', React); vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true);
  preference = new EventTarget();
  vi.stubGlobal('matchMedia', () => preference);
  vi.stubGlobal('requestAnimationFrame', (fn: FrameRequestCallback) => { fn(0); return 1; });
  vi.stubGlobal('cancelAnimationFrame', vi.fn());
  const finished = new Promise<void>(resolve => { finish = resolve; });
  getAnimations = vi.fn(() => [{ effect: { getComputedTiming: () => ({ iterations: 1 }) }, finished }]);
  Object.defineProperty(Element.prototype, 'getAnimations', { configurable: true, value: getAnimations });
  container = document.createElement('div'); document.body.append(container); root = createRoot(container);
});
afterEach(async () => { await act(async () => root.unmount()); container.remove(); delete (Element.prototype as Partial<Element>).getAnimations; vi.restoreAllMocks(); vi.unstubAllGlobals(); });
async function mount() {
  await act(async () => root.render(<><button id="outside">Outside</button><IntroHandoff product={<h1>Product</h1>}><a href="/download">Install</a><a href="/docs">Docs</a></IntroHandoff></>));
}
it('keeps focused intro controls visible until focus leaves the boundary', async () => {
  await mount(); const links = container.querySelectorAll('a'); links[0].focus();
  await act(async () => finish());
  expect(container.querySelector<HTMLElement>('[data-site-intro]')!.hidden).toBe(false);
  expect(document.activeElement).toBe(links[0]);
  await act(async () => links[1].focus());
  expect(container.querySelector<HTMLElement>('[data-site-intro]')!.hidden).toBe(false);
  await act(async () => container.querySelector<HTMLButtonElement>('#outside')!.focus());
  expect(container.querySelector<HTMLElement>('[data-site-intro]')!.hidden).toBe(true);
  expect(document.activeElement?.id).toBe('outside');
});
it('does not steal focus outside the intro when finite animations finish', async () => {
  await mount(); container.querySelector<HTMLButtonElement>('#outside')!.focus();
  await act(async () => finish());
  expect(container.querySelector<HTMLElement>('[data-site-intro]')!.hidden).toBe(true);
  expect(document.activeElement?.id).toBe('outside');
});
it('keeps the intro available without animation inspection', async () => {
  delete (Element.prototype as Partial<Element>).getAnimations; await mount();
  await act(async () => finish());
  expect(container.querySelector<HTMLElement>('[data-site-intro]')!.hidden).toBe(false);
});
it('resamples finite animations when the motion preference changes', async () => {
  await mount(); let finishReplacement!: () => void;
  const finished = new Promise<void>(resolve => { finishReplacement = resolve; });
  getAnimations.mockReturnValue([{ effect: { getComputedTiming: () => ({ iterations: 1 }) }, finished }]);
  await act(async () => { preference.dispatchEvent(new Event('change')); finish(); });
  expect(getAnimations).toHaveBeenCalledTimes(2);
  expect(container.querySelector<HTMLElement>('[data-site-intro]')!.hidden).toBe(false);
  await act(async () => finishReplacement());
  expect(container.querySelector<HTMLElement>('[data-site-intro]')!.hidden).toBe(true);
});
it('removes the preference observer and ignores completion after unmount', async () => {
  const remove = vi.spyOn(preference, 'removeEventListener'); await mount();
  await act(async () => root.render(null)); await act(async () => finish());
  expect(remove).toHaveBeenCalledWith('change', expect.any(Function));
  preference.dispatchEvent(new Event('change')); expect(getAnimations).toHaveBeenCalledTimes(1);
});
it('keeps home to explore, but explore enters the generated app rather than itself', async () => {
  await act(async () => root.render(<ProductIntroduction />));
  expect(container.querySelector('.product-entry-actions a')?.getAttribute('href')).toBe('/explore');
  await act(async () => root.render(<ExplorePage />));
  expect(container.querySelector('.product-entry-actions a')?.getAttribute('href')).toBe('/demo-app/terminal');
  expect(container.querySelector('.product-entry-actions a')?.textContent).toContain('Choose a layout');
  expect(container.textContent).not.toMatch(/pending visual acceptance|current workspace imagery/i);
  expect(container.textContent).toContain('No broker is connected and no orders are sent.');
});
