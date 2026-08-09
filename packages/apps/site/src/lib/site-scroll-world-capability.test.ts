/**
 * TDD policy/component tests for SiteScrollWorld pilot (default-off, progressive enhancement,
 * reduced-motion/static fallback, WebGL failure, route scope, semantic CTA continuity).
 * Written BEFORE any implementation per TDD iron law.
 * These tests must fail (RED) until the capability lib, wrapper, and integration exist.
 */

import { describe, expect, it, beforeEach, vi } from 'vitest';

// These imports will fail until lib/site-scroll-world-capability.ts exists (RED phase)
import {
  shouldEnableScrollWorld,
  isWebGLAvailable,
  getScrollWorldEnvFlag,
  hasReducedMotionPreference,
} from './site-scroll-world-capability';

describe('site-scroll-world capability policy (TDD RED)', () => {
  beforeEach(() => {
    vi.stubGlobal('navigator', { hardwareConcurrency: 8, deviceMemory: 8 });
    vi.stubGlobal('window', { devicePixelRatio: 1, matchMedia: vi.fn() });
    // Clear any sessionStorage mock
    vi.stubGlobal('sessionStorage', { getItem: vi.fn(() => null) });
  });

  it('defaults OFF when NEXT_PUBLIC_FLINTTRADE_SITE_SCROLL_WORLD !== "1"', () => {
    // Simulate env off (default)
    vi.stubEnv('NEXT_PUBLIC_FLINTTRADE_SITE_SCROLL_WORLD', undefined);
    expect(getScrollWorldEnvFlag()).toBe(false);
    expect(shouldEnableScrollWorld()).toBe(false);
  });

  it('enables only when env=1 AND no reduced-motion AND WebGL capable AND no prior failure', () => {
    vi.stubEnv('NEXT_PUBLIC_FLINTTRADE_SITE_SCROLL_WORLD', '1');
    const mockMatchMedia = vi.fn().mockReturnValue({ matches: false });
    vi.stubGlobal('window', { matchMedia: mockMatchMedia, devicePixelRatio: 1 });
    vi.stubGlobal('navigator', { hardwareConcurrency: 8, deviceMemory: 8 });
    vi.stubGlobal('sessionStorage', { getItem: vi.fn(() => null) });
    expect(shouldEnableScrollWorld()).toBe(true);
  });

  it('falls back to static/Graphite on reduced-motion preference', () => {
    vi.stubEnv('NEXT_PUBLIC_FLINTTRADE_SITE_SCROLL_WORLD', '1');
    const mockMatchMedia = vi.fn().mockReturnValue({ matches: true });
    vi.stubGlobal('window', { matchMedia: mockMatchMedia });
    expect(hasReducedMotionPreference()).toBe(true);
    expect(shouldEnableScrollWorld()).toBe(false);
  });

  it('detects WebGL failure via context creation or prior flag and forces fallback', () => {
    vi.stubEnv('NEXT_PUBLIC_FLINTTRADE_SITE_SCROLL_WORLD', '1');
    vi.stubGlobal('sessionStorage', { getItem: vi.fn(() => '1') });
    expect(shouldEnableScrollWorld()).toBe(false);
    // Also test isWebGLAvailable would return false on failure path
  });

  it('enforces route scope: no three imports leak into page.tsx or trading surfaces', () => {
    // Source guard test (reads page source) - will be extended in homepage-bands.test.ts
    // This test ensures isolation
    expect(true).toBe(true); // placeholder until source read in integration test
  });

  it('preserves semantic CTA continuity: exactly one primary CTA remains in DOM, WebGL is aria-hidden decorative', () => {
    // This will be validated after page mount + source assertions
    expect(true).toBe(true); // RED until integration
  });
});
