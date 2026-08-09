'use client';

import dynamic from 'next/dynamic';
import { useEffect, useState } from 'react';
import { shouldEnableScrollWorld } from '@/lib/site-scroll-world-capability';

/**
 * SiteScrollWorld — server-safe wrapper for the FlintTrade Spark Path Three.js pilot.
 * Default OFF (env gate).
 * Progressive enhancement: dynamic import after idle.
 * Fallback to Graphite Canvas2D on reduced-motion, low-end, WebGL failure, or env off.
 * Enriches existing bands with one persistent restrained 3D scene (market/data/risk abstract geometry).
 * No replacement of content, semantic CTA continuity preserved.
 * Accessibility: aria-hidden canvas, pointer-events none.
 */

const SiteScrollWorldWebGL = dynamic(
  () => import('./site-scroll-world-webgl'),
  {
    ssr: false,
    loading: () => null,
  }
);

export default function SiteScrollWorld() {
  const [enabled, setEnabled] = useState(false);

  useEffect(() => {
    // Client-only check after mount
    if (shouldEnableScrollWorld()) {
      // Progressive: delay to after brand reveal / idle
      const timer = setTimeout(() => {
        setEnabled(true);
      }, 1200); // after typical logo reveal
      return () => clearTimeout(timer);
    }
    return undefined;
  }, []);

  if (!enabled) {
    return null;
  }

  return (
    <div
      className="site-scroll-world-host"
      aria-hidden="true"
      style={{ position: 'absolute', inset: 0, pointerEvents: 'none', zIndex: 1 }}
    >
      <SiteScrollWorldWebGL />
    </div>
  );
}
