/** @vitest-environment jsdom */

import { act, createElement } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const capability = vi.hoisted(() => ({ read: vi.fn() }));
const dynamicState = vi.hoisted(() => ({
  renders: 0,
  onReady: undefined as (() => void) | undefined,
  onFallback: undefined as ((reason: string) => void) | undefined,
}));

vi.mock('@/lib/site-scroll-world-capability', () => ({
  readScrollWorldCapability: capability.read,
  SCROLL_WORLD_FAILURE_KEY: 'ft-site-scroll-world-failed',
}));

vi.mock('next/dynamic', async () => {
  const React = await vi.importActual<typeof import('react')>('react');
  return {
    default: () => function MockWebGL(props: {
      onReady: () => void;
      onFallback: (reason: string) => void;
    }) {
      dynamicState.renders += 1;
      dynamicState.onReady = props.onReady;
      dynamicState.onFallback = props.onFallback;
      return React.createElement('canvas', { className: 'mock-webgl-child', 'aria-hidden': 'true' });
    },
  };
});

import SiteScrollWorld from './site-scroll-world';

describe('SiteScrollWorld progressive wrapper', () => {
  let container: HTMLDivElement;
  let root: Root;
  let idleCallback: IdleRequestCallback | undefined;
  let mediaChange: ((event: MediaQueryListEvent) => void) | undefined;

  beforeEach(() => {
    vi.useFakeTimers();
    capability.read.mockReset();
    dynamicState.renders = 0;
    dynamicState.onReady = undefined;
    dynamicState.onFallback = undefined;
    idleCallback = undefined;
    mediaChange = undefined;
    sessionStorage.clear();
    document.documentElement.className = '';
    (globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

    vi.stubGlobal('requestIdleCallback', vi.fn((callback: IdleRequestCallback) => {
      idleCallback = callback;
      return 41;
    }));
    vi.stubGlobal('cancelIdleCallback', vi.fn());
    vi.stubGlobal('matchMedia', vi.fn());
    window.matchMedia = vi.fn(() => ({
      matches: false,
      media: '(prefers-reduced-motion: reduce)',
      onchange: null,
      addEventListener: (_type: string, listener: EventListenerOrEventListenerObject) => {
        mediaChange = listener as (event: MediaQueryListEvent) => void;
      },
      removeEventListener: vi.fn(),
      addListener: vi.fn(),
      removeListener: vi.fn(),
      dispatchEvent: vi.fn(),
    }));

    container = document.createElement('div');
    document.body.append(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  async function renderWrapper() {
    await act(async () => root.render(createElement(SiteScrollWorld)));
  }

  async function finishProgressiveLoad() {
    await act(async () => vi.advanceTimersByTime(1_200));
    expect(container.querySelector('.site-scroll-world-host')).toBeNull();
    await act(async () => idleCallback?.({ didTimeout: false, timeRemaining: () => 8 }));
  }

  it('renders no host and never renders the dynamic module while the flag/capability policy is off', async () => {
    capability.read.mockReturnValue({ enabled: false, reason: 'flag-off' });
    await renderWrapper();
    await act(async () => vi.runAllTimers());

    expect(container.querySelector('.site-scroll-world-host')).toBeNull();
    expect(dynamicState.renders).toBe(0);
    expect(document.documentElement.classList.contains('ft-scroll-world-on')).toBe(false);
  });

  it('waits for both the reveal delay and browser idle before mounting the decorative client-only layer', async () => {
    capability.read.mockReturnValue({ enabled: true, reason: 'enabled' });
    await renderWrapper();
    await finishProgressiveLoad();

    const host = container.querySelector<HTMLElement>('.site-scroll-world-host');
    expect(host).not.toBeNull();
    expect(host?.getAttribute('aria-hidden')).toBe('true');
    expect(host?.style.pointerEvents).toBe('none');
    expect(dynamicState.renders).toBe(1);
    expect(container.querySelector('.mock-webgl-child')).not.toBeNull();
    expect(document.documentElement.classList.contains('ft-scroll-world-on')).toBe(false);
  });

  it('promotes only after the real child ready callback, then persists the exact failure key on child fallback', async () => {
    capability.read.mockReturnValue({ enabled: true, reason: 'enabled' });
    await renderWrapper();
    await finishProgressiveLoad();

    await act(async () => dynamicState.onReady?.());
    expect(document.documentElement.classList.contains('ft-scroll-world-on')).toBe(true);

    await act(async () => dynamicState.onFallback?.('context-lost'));

    expect(container.querySelector('.site-scroll-world-host')).toBeNull();
    expect(document.documentElement.classList.contains('ft-scroll-world-fallback')).toBe(true);
    expect(document.documentElement.classList.contains('ft-scroll-world-on')).toBe(false);
    expect(sessionStorage.getItem('ft-site-scroll-world-failed')).toBe('1');
    expect(sessionStorage.getItem('undefined')).toBeNull();
  });

  it('responds to a live reduced-motion preference change and keeps the static fallback', async () => {
    capability.read
      .mockReturnValueOnce({ enabled: true, reason: 'enabled' })
      .mockReturnValue({ enabled: false, reason: 'reduced-motion' });
    await renderWrapper();
    await finishProgressiveLoad();

    await act(async () => {
      mediaChange?.({ matches: true } as MediaQueryListEvent);
    });

    expect(container.querySelector('.site-scroll-world-host')).toBeNull();
    expect(document.documentElement.classList.contains('ft-scroll-world-fallback')).toBe(true);
  });

  it('does not apply post-activation fallback when preflight rejects before WebGL mounts', async () => {
    capability.read.mockReturnValue({ enabled: false, reason: 'mobile' });
    await renderWrapper();
    await act(async () => vi.runAllTimers());

    expect(container.querySelector('.site-scroll-world-host')).toBeNull();
    expect(dynamicState.renders).toBe(0);
    expect(document.documentElement.classList.contains('ft-scroll-world-fallback')).toBe(false);
    expect(document.documentElement.classList.contains('ft-scroll-world-on')).toBe(false);
  });
});
