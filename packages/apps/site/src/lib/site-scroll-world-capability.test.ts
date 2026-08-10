/** @vitest-environment jsdom */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import {
  evaluateScrollWorldCapability,
  getScrollWorldEnvFlag,
  readScrollWorldCapability,
  SCROLL_WORLD_FAILURE_KEY,
  type ScrollWorldCapabilityInput,
} from './site-scroll-world-capability';

const capableInput: ScrollWorldCapabilityInput = {
  flagEnabled: true,
  prefersReducedMotion: false,
  priorFailure: false,
  webglAvailable: true,
  hardwareConcurrency: 8,
  deviceMemory: 8,
  devicePixelRatio: 1,
  viewportWidth: 1440,
  saveData: false,
};

beforeEach(() => {
  sessionStorage.clear();
  Object.defineProperty(window, 'innerWidth', { configurable: true, value: 1440 });
  Object.defineProperty(window, 'devicePixelRatio', { configurable: true, value: 1 });
  Object.defineProperty(navigator, 'hardwareConcurrency', { configurable: true, value: 8 });
  Object.defineProperty(navigator, 'deviceMemory', { configurable: true, value: 8 });
  Object.defineProperty(navigator, 'connection', { configurable: true, value: { saveData: false } });
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
});

afterEach(() => {
  vi.unstubAllEnvs();
  vi.restoreAllMocks();
  sessionStorage.clear();
});

function mockCanvasContexts(resolveContext: (contextId: string) => unknown) {
  return vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockImplementation(
    ((contextId: string) => resolveContext(contextId)) as typeof HTMLCanvasElement.prototype.getContext,
  );
}

function fakeWebGLContext() {
  const loseContext = vi.fn();
  return {
    context: {
      getExtension: vi.fn((name: string) => (name === 'WEBGL_lose_context' ? { loseContext } : null)),
    },
    loseContext,
  };
}

describe('site scroll-world capability policy', () => {
  it('is default-off unless the public flag is exactly 1', () => {
    vi.stubEnv('NEXT_PUBLIC_FLINTTRADE_SITE_SCROLL_WORLD', undefined);
    expect(getScrollWorldEnvFlag()).toBe(false);

    vi.stubEnv('NEXT_PUBLIC_FLINTTRADE_SITE_SCROLL_WORLD', 'true');
    expect(getScrollWorldEnvFlag()).toBe(false);

    vi.stubEnv('NEXT_PUBLIC_FLINTTRADE_SITE_SCROLL_WORLD', '1');
    expect(getScrollWorldEnvFlag()).toBe(true);
  });

  it('allows progressive enhancement only for a capable motion-OK desktop', () => {
    expect(evaluateScrollWorldCapability(capableInput)).toEqual({ enabled: true, reason: 'enabled' });
  });

  it.each([
    [{ flagEnabled: false }, 'flag-off'],
    [{ prefersReducedMotion: true }, 'reduced-motion'],
    [{ priorFailure: true }, 'prior-failure'],
    [{ webglAvailable: false }, 'webgl-unavailable'],
    [{ hardwareConcurrency: 4 }, 'low-end-cpu'],
    [{ deviceMemory: 4 }, 'low-memory'],
    [{ viewportWidth: 899, devicePixelRatio: 1 }, 'mobile-viewport'],
    [{ saveData: true }, 'save-data'],
  ] as const)('fails open to Graphite for %s', (patch, reason) => {
    expect(evaluateScrollWorldCapability({ ...capableInput, ...patch })).toEqual({ enabled: false, reason });
  });

  it('reads a real WebGL2 capability and releases the probe context', () => {
    vi.stubEnv('NEXT_PUBLIC_FLINTTRADE_SITE_SCROLL_WORLD', '1');
    const { context, loseContext } = fakeWebGLContext();
    const getContext = mockCanvasContexts((contextId) => (contextId === 'webgl2' ? context : null));

    expect(readScrollWorldCapability()).toEqual({ enabled: true, reason: 'enabled' });
    expect(getContext).toHaveBeenCalledTimes(1);
    expect(getContext).toHaveBeenCalledWith('webgl2', { failIfMajorPerformanceCaveat: true });
    expect(loseContext).toHaveBeenCalledOnce();
  });

  it('falls back from WebGL2 to a real WebGL1 probe', () => {
    vi.stubEnv('NEXT_PUBLIC_FLINTTRADE_SITE_SCROLL_WORLD', '1');
    const { context, loseContext } = fakeWebGLContext();
    const getContext = mockCanvasContexts((contextId) => (contextId === 'webgl' ? context : null));

    expect(readScrollWorldCapability()).toEqual({ enabled: true, reason: 'enabled' });
    expect(getContext.mock.calls.map(([contextId]) => contextId)).toEqual(['webgl2', 'webgl']);
    expect(loseContext).toHaveBeenCalledOnce();
  });

  it('fails open when both WebGL probes return null or probing throws', () => {
    vi.stubEnv('NEXT_PUBLIC_FLINTTRADE_SITE_SCROLL_WORLD', '1');
    mockCanvasContexts(() => null);
    expect(readScrollWorldCapability()).toEqual({ enabled: false, reason: 'webgl-unavailable' });

    vi.restoreAllMocks();
    mockCanvasContexts(() => {
      throw new Error('synthetic context failure');
    });
    expect(readScrollWorldCapability()).toEqual({ enabled: false, reason: 'webgl-unavailable' });
  });

  it('short-circuits mobile and exact prior-failure gates before creating any WebGL context', () => {
    vi.stubEnv('NEXT_PUBLIC_FLINTTRADE_SITE_SCROLL_WORLD', '1');
    const getContext = mockCanvasContexts(() => {
      throw new Error('must not probe');
    });
    Object.defineProperty(window, 'innerWidth', { configurable: true, value: 390 });
    Object.defineProperty(window, 'devicePixelRatio', { configurable: true, value: 1 });
    expect(readScrollWorldCapability()).toEqual({ enabled: false, reason: 'mobile-viewport' });
    expect(getContext).not.toHaveBeenCalled();

    Object.defineProperty(window, 'innerWidth', { configurable: true, value: 1440 });
    sessionStorage.setItem(SCROLL_WORLD_FAILURE_KEY, '1');
    expect(readScrollWorldCapability()).toEqual({ enabled: false, reason: 'prior-failure' });
    expect(getContext).not.toHaveBeenCalled();
  });

  it('does not reject missing optional hardware hints', () => {
    expect(
      evaluateScrollWorldCapability({
        ...capableInput,
        hardwareConcurrency: undefined,
        deviceMemory: undefined,
      }),
    ).toEqual({ enabled: true, reason: 'enabled' });
  });
});
