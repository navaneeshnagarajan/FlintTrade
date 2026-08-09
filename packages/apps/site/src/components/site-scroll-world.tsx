'use client';

import dynamic from 'next/dynamic';
import { useCallback, useEffect, useRef, useState } from 'react';

import {
  readScrollWorldCapability,
  SCROLL_WORLD_FAILURE_KEY,
  type ScrollWorldCapabilityReason,
} from '@/lib/site-scroll-world-capability';

export type ScrollWorldFailureReason =
  | ScrollWorldCapabilityReason
  | 'chunk-error'
  | 'renderer-error'
  | 'setup-error'
  | 'render-error'
  | 'context-lost'
  | 'missing-chapters';

interface SiteScrollWorldWebGLProps {
  onReady: () => void;
  onFallback: (reason: ScrollWorldFailureReason) => void;
}

interface ScrollWorldFailureDetail {
  reason?: ScrollWorldFailureReason;
}

const REVEAL_DELAY_MS = 1_100;
const IDLE_TIMEOUT_MS = 1_500;

const SiteScrollWorldWebGL = dynamic<SiteScrollWorldWebGLProps>(
  () =>
    import('./site-scroll-world-webgl').catch(() => {
      if (typeof window !== 'undefined') {
        queueMicrotask(() => {
          window.dispatchEvent(
            new CustomEvent<ScrollWorldFailureDetail>('ft-scroll-world-failure', {
              detail: { reason: 'chunk-error' },
            }),
          );
        });
      }
      return { default: () => null };
    }),
  { ssr: false, loading: () => null },
);

function isPersistentFailure(reason: ScrollWorldFailureReason): boolean {
  return ['chunk-error', 'renderer-error', 'setup-error', 'render-error', 'context-lost'].includes(reason);
}

function applyFallbackMarker(reason: ScrollWorldFailureReason): void {
  const root = document.documentElement;
  root.classList.remove('ft-scroll-world-on');
  root.classList.add('ft-scroll-world-fallback');
  root.classList.toggle('no-webgl', reason === 'webgl-unavailable' || isPersistentFailure(reason));
  window.dispatchEvent(new CustomEvent('ft-scroll-world-fallback'));
}

function clearScrollWorldMarkers(): void {
  document.documentElement.classList.remove('ft-scroll-world-on', 'ft-scroll-world-fallback', 'no-webgl');
}

function scheduleProgressiveMount(callback: () => void): () => void {
  let idleId: number | undefined;
  let fallbackTimer: ReturnType<typeof setTimeout> | undefined;

  const revealTimer = setTimeout(() => {
    if (typeof requestIdleCallback === 'function') {
      idleId = requestIdleCallback(callback, { timeout: IDLE_TIMEOUT_MS });
    } else {
      fallbackTimer = setTimeout(callback, 0);
    }
  }, REVEAL_DELAY_MS);

  return () => {
    clearTimeout(revealTimer);
    if (idleId !== undefined && typeof cancelIdleCallback === 'function') cancelIdleCallback(idleId);
    if (fallbackTimer !== undefined) clearTimeout(fallbackTimer);
  };
}

/**
 * Default-off client island. It does not render (and therefore does not request
 * the Three.js chunk) until capability gates, the brand reveal delay and an
 * idle callback have all passed.
 */
export default function SiteScrollWorld() {
  const [mounted, setMounted] = useState(false);
  const cancelScheduleRef = useRef<(() => void) | null>(null);
  const permanentlyFailedRef = useRef(false);

  const stopSchedule = useCallback(() => {
    cancelScheduleRef.current?.();
    cancelScheduleRef.current = null;
  }, []);

  const handleFallback = useCallback((reason: ScrollWorldFailureReason) => {
    stopSchedule();
    setMounted(false);
    if (isPersistentFailure(reason)) {
      permanentlyFailedRef.current = true;
      try {
        sessionStorage.setItem(SCROLL_WORLD_FAILURE_KEY, '1');
      } catch {
        // Storage can be unavailable; the in-memory failure still fails open.
      }
    }
    applyFallbackMarker(reason);
  }, [stopSchedule]);

  const handleReady = useCallback(() => {
    const root = document.documentElement;
    root.classList.remove('ft-scroll-world-fallback', 'no-webgl');
    root.classList.add('ft-scroll-world-on');
    window.dispatchEvent(new CustomEvent('ft-scroll-world-ready'));
  }, []);

  useEffect(() => {
    let disposed = false;
    const motionQuery = window.matchMedia('(prefers-reduced-motion: reduce)');

    const evaluateAndSchedule = () => {
      stopSchedule();
      if (permanentlyFailedRef.current) {
        handleFallback('prior-failure');
        return;
      }

      const capability = readScrollWorldCapability();
      if (!capability.enabled) {
        setMounted(false);
        if (capability.reason === 'flag-off') {
          clearScrollWorldMarkers();
        } else {
          applyFallbackMarker(capability.reason);
        }
        return;
      }

      clearScrollWorldMarkers();
      cancelScheduleRef.current = scheduleProgressiveMount(() => {
        if (!disposed && !permanentlyFailedRef.current) setMounted(true);
      });
    };

    const onFailure = (event: Event) => {
      const detail = (event as CustomEvent<ScrollWorldFailureDetail>).detail;
      handleFallback(detail?.reason ?? 'render-error');
    };

    motionQuery.addEventListener('change', evaluateAndSchedule);
    window.addEventListener('ft-scroll-world-failure', onFailure);
    evaluateAndSchedule();

    return () => {
      disposed = true;
      stopSchedule();
      motionQuery.removeEventListener('change', evaluateAndSchedule);
      window.removeEventListener('ft-scroll-world-failure', onFailure);
      clearScrollWorldMarkers();
      window.dispatchEvent(new CustomEvent('ft-scroll-world-fallback'));
    };
  }, [handleFallback, stopSchedule]);

  if (!mounted) return null;

  return (
    <div
      className="site-scroll-world-host"
      aria-hidden="true"
      style={{ position: 'absolute', inset: 0, pointerEvents: 'none', zIndex: 1 }}
    >
      <SiteScrollWorldWebGL onReady={handleReady} onFallback={handleFallback} />
    </div>
  );
}
