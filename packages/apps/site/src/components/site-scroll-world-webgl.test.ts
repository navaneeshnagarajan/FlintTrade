/** @vitest-environment jsdom */

import { act, createElement } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const rendererState = vi.hoisted(() => ({
  instances: [] as Array<{
    dispose: ReturnType<typeof vi.fn>;
    forceContextLoss: ReturnType<typeof vi.fn>;
    render: ReturnType<typeof vi.fn>;
  }>,
  throwOnRender: false,
  throwOnSetSize: false,
}));

vi.mock('three', async () => {
  const actual = await vi.importActual<typeof import('three')>('three');

  class MockWebGLRenderer {
    outputColorSpace = actual.SRGBColorSpace;
    toneMapping = actual.NoToneMapping;
    toneMappingExposure = 1;
    shadowMap = { enabled: false };
    info = { render: { calls: 1, triangles: 144 } };
    dispose = vi.fn();
    forceContextLoss = vi.fn();
    setPixelRatio = vi.fn();
    setSize = vi.fn(() => {
      if (rendererState.throwOnSetSize) throw new Error('synthetic scene setup failure');
    });
    render = vi.fn(() => {
      if (rendererState.throwOnRender) throw new Error('synthetic scene render failure');
    });

    constructor() {
      rendererState.instances.push(this);
    }
  }

  return { ...actual, WebGLRenderer: MockWebGLRenderer };
});

import SiteScrollWorldWebGL from './site-scroll-world-webgl';

describe('SiteScrollWorldWebGL child integration lifecycle', () => {
  let container: HTMLDivElement;
  let root: Root;
  let rootMounted: boolean;
  let animationFrame: FrameRequestCallback | undefined;

  beforeEach(() => {
    rendererState.instances.length = 0;
    rendererState.throwOnRender = false;
    rendererState.throwOnSetSize = false;
    animationFrame = undefined;
    document.body.replaceChildren();
    Object.defineProperty(window, 'innerWidth', { configurable: true, value: 1440 });
    Object.defineProperty(window, 'innerHeight', { configurable: true, value: 900 });
    Object.defineProperty(window, 'devicePixelRatio', { configurable: true, value: 1 });
    Object.defineProperty(window, 'scrollY', { configurable: true, value: 0 });
    Object.defineProperty(document.documentElement, 'scrollHeight', { configurable: true, value: 5_000 });
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
    vi.stubGlobal('requestAnimationFrame', vi.fn((callback: FrameRequestCallback) => {
      animationFrame = callback;
      return 71;
    }));
    vi.stubGlobal('cancelAnimationFrame', vi.fn());

    for (let chapter = 0; chapter <= 5; chapter += 1) {
      const anchor = document.createElement('section');
      anchor.dataset.scrollChapter = String(chapter);
      anchor.getBoundingClientRect = () => ({
        x: 0,
        y: chapter * 800,
        top: chapter * 800,
        right: 100,
        bottom: chapter * 800 + 100,
        left: 0,
        width: 100,
        height: 100,
        toJSON: () => ({}),
      });
      document.body.append(anchor);
    }

    container = document.createElement('div');
    document.body.append(container);
    root = createRoot(container);
    rootMounted = true;
    (globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  });

  afterEach(async () => {
    if (rootMounted) await act(async () => root.unmount());
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it('reports a real canvas context-loss event and tears the renderer down exactly once', async () => {
    const onReady = vi.fn();
    const onFallback = vi.fn();
    await act(async () => root.render(createElement(SiteScrollWorldWebGL, { onReady, onFallback })));

    const canvas = container.querySelector('canvas');
    const renderer = rendererState.instances[0];
    await act(async () => animationFrame?.(16));
    expect(canvas).not.toBeNull();
    expect(renderer).toBeDefined();
    expect({
      renderCalls: renderer.render.mock.calls.length,
      readyCalls: onReady.mock.calls,
      fallbackCalls: onFallback.mock.calls,
      disposeCalls: renderer.dispose.mock.calls.length,
      canvasState: canvas?.dataset.animationState,
    }).toEqual({
      renderCalls: 1,
      readyCalls: [[]],
      fallbackCalls: [],
      disposeCalls: 0,
      canvasState: 'running',
    });

    const contextLoss = new Event('webglcontextlost', { cancelable: true });
    await act(async () => canvas?.dispatchEvent(contextLoss));
    await act(async () => root.unmount());
    rootMounted = false;

    expect(contextLoss.defaultPrevented).toBe(true);
    expect(onFallback).toHaveBeenCalledTimes(1);
    expect(onFallback).toHaveBeenCalledWith('context-lost');
    expect(renderer.dispose).toHaveBeenCalledTimes(1);
    expect(renderer.forceContextLoss).not.toHaveBeenCalled();
  });

  it('fails closed without poisoning the canvas when scene setup throws after renderer creation', async () => {
    rendererState.throwOnSetSize = true;
    const onReady = vi.fn();
    const onFallback = vi.fn();

    await act(async () => root.render(createElement(SiteScrollWorldWebGL, { onReady, onFallback })));
    const renderer = rendererState.instances[0];

    expect(onReady).not.toHaveBeenCalled();
    expect(onFallback).toHaveBeenCalledTimes(1);
    expect(onFallback).toHaveBeenCalledWith('setup-error');
    expect(renderer.dispose).toHaveBeenCalledTimes(1);
    expect(renderer.forceContextLoss).not.toHaveBeenCalled();
  });
});
