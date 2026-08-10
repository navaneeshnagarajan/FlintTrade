/**
 * Pure and browser capability policy for the optional Spark Path enhancement.
 * The flag is default-off and every failure returns the complete Graphite baseline.
 * This module deliberately has no Three.js import.
 */

export const SCROLL_WORLD_FAILURE_KEY = 'ft-site-scroll-world-failed';

export type ScrollWorldCapabilityReason =
  | 'enabled'
  | 'flag-off'
  | 'reduced-motion'
  | 'prior-failure'
  | 'webgl-unavailable'
  | 'low-end-cpu'
  | 'low-memory'
  | 'mobile-viewport'
  | 'save-data';

export interface ScrollWorldCapabilityInput {
  flagEnabled: boolean;
  prefersReducedMotion: boolean;
  priorFailure: boolean;
  webglAvailable: boolean;
  hardwareConcurrency?: number;
  deviceMemory?: number;
  devicePixelRatio: number;
  viewportWidth: number;
  saveData: boolean;
}

export interface ScrollWorldCapability {
  enabled: boolean;
  reason: ScrollWorldCapabilityReason;
}

interface NavigatorWithHints extends Navigator {
  deviceMemory?: number;
  connection?: { saveData?: boolean };
}

export function getScrollWorldEnvFlag(): boolean {
  return typeof process !== 'undefined' && process.env.NEXT_PUBLIC_FLINTTRADE_SITE_SCROLL_WORLD === '1';
}

export function hasReducedMotionPreference(): boolean {
  if (typeof window === 'undefined') return false;
  try {
    return window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  } catch {
    return false;
  }
}

export function hasPriorScrollWorldFailure(): boolean {
  if (typeof sessionStorage === 'undefined') return false;
  try {
    return sessionStorage.getItem(SCROLL_WORLD_FAILURE_KEY) === '1';
  } catch {
    return true;
  }
}

export function isWebGLAvailable(): boolean {
  if (typeof document === 'undefined') return false;
  try {
    const canvas = document.createElement('canvas');
    const attributes: WebGLContextAttributes = { failIfMajorPerformanceCaveat: true };
    const context =
      canvas.getContext('webgl2', attributes) ??
      canvas.getContext('webgl', attributes);
    if (!context) return false;
    context.getExtension('WEBGL_lose_context')?.loseContext();
    return true;
  } catch {
    return false;
  }
}

export function evaluateScrollWorldCapability(input: ScrollWorldCapabilityInput): ScrollWorldCapability {
  if (!input.flagEnabled) return { enabled: false, reason: 'flag-off' };
  if (input.prefersReducedMotion) return { enabled: false, reason: 'reduced-motion' };
  if (input.priorFailure) return { enabled: false, reason: 'prior-failure' };
  if (input.hardwareConcurrency !== undefined && input.hardwareConcurrency <= 4) {
    return { enabled: false, reason: 'low-end-cpu' };
  }
  if (input.deviceMemory !== undefined && input.deviceMemory <= 4) {
    return { enabled: false, reason: 'low-memory' };
  }
  if (input.viewportWidth < 900) {
    return { enabled: false, reason: 'mobile-viewport' };
  }
  if (input.saveData) return { enabled: false, reason: 'save-data' };
  if (!input.webglAvailable) return { enabled: false, reason: 'webgl-unavailable' };
  return { enabled: true, reason: 'enabled' };
}

export function readScrollWorldCapability(): ScrollWorldCapability {
  if (typeof window === 'undefined' || typeof navigator === 'undefined') {
    return { enabled: false, reason: 'webgl-unavailable' };
  }

  const browserNavigator = navigator as NavigatorWithHints;
  const inputWithoutWebGL: ScrollWorldCapabilityInput = {
    flagEnabled: getScrollWorldEnvFlag(),
    prefersReducedMotion: hasReducedMotionPreference(),
    priorFailure: hasPriorScrollWorldFailure(),
    webglAvailable: true,
    hardwareConcurrency: browserNavigator.hardwareConcurrency || undefined,
    deviceMemory: browserNavigator.deviceMemory,
    devicePixelRatio: window.devicePixelRatio || 1,
    viewportWidth: window.innerWidth,
    saveData: browserNavigator.connection?.saveData === true,
  };

  const preflight = evaluateScrollWorldCapability(inputWithoutWebGL);
  if (!preflight.enabled) return preflight;

  return evaluateScrollWorldCapability({
    ...inputWithoutWebGL,
    webglAvailable: isWebGLAvailable(),
  });
}

export function shouldEnableScrollWorld(): boolean {
  return readScrollWorldCapability().enabled;
}
