/**
 * SiteScrollWorld capability policy — pure predicates for default-off,
 * reduced-motion, WebGL failure, progressive enhancement gates.
 * No three.js import here; client-only dynamic load in wrapper.
 * TDD GREEN: minimal impl to satisfy the policy tests written first.
 */

export function getScrollWorldEnvFlag(): boolean {
  if (typeof process === 'undefined') return false;
  return process.env.NEXT_PUBLIC_FLINTTRADE_SITE_SCROLL_WORLD === '1';
}

export function hasReducedMotionPreference(): boolean {
  if (typeof window === 'undefined') return false;
  try {
    return window.matchMedia?.('(prefers-reduced-motion: reduce)')?.matches ?? false;
  } catch {
    return false;
  }
}

export function isWebGLAvailable(): boolean {
  if (typeof window === 'undefined' || typeof document === 'undefined') return false;
  try {
    const canvas = document.createElement('canvas');
    const gl = canvas.getContext('webgl2', { failIfMajorPerformanceCaveat: true }) ||
               canvas.getContext('webgl', { failIfMajorPerformanceCaveat: true });
    if (!gl) return false;
    // Simulate prior failure flag check (sessionStorage set by webgl module on context loss)
    const failed = typeof sessionStorage !== 'undefined' && sessionStorage.getItem('ft-site-scroll-world-failed') === '1';
    if (failed) return false;
    return true;
  } catch {
    return false;
  }
}

export function shouldEnableScrollWorld(): boolean {
  if (!getScrollWorldEnvFlag()) return false;
  if (hasReducedMotionPreference()) return false;
  if (!isWebGLAvailable()) return false;
  // Progressive: low-end hardware guard (concurrency <=4 or memory <=4)
  if (typeof navigator !== 'undefined') {
    const hc = navigator.hardwareConcurrency ?? 8;
    const mem = (navigator as any).deviceMemory ?? 8;
    if (hc <= 4 || mem <= 4) return false;
  }
  return true;
}
