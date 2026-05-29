/**
 * Particles.tsx
 *
 * Canvas-based decorative particle system with four behaviors:
 *   drift  — slow diagonal bounce (original behavior)
 *   float  — smooth sine-wave vertical bobbing
 *   pulse  — opacity oscillation in place (max 2 Hz, min 500ms transition)
 *   snow   — top-to-bottom downward drift with lateral wander
 *
 * Accessibility:
 *   - canvas has aria-hidden="true" (decorative, never interactive)
 *   - Returns null when prefers-reduced-motion is set (OS/browser) OR when
 *     themeStore.reduceMotion is true (user override)
 *   - Low-end device auto-downgrade: navigator.hardwareConcurrency <= 4
 *     reduces quantity by 50% to avoid jank
 *
 * Performance:
 *   - IntersectionObserver pauses requestAnimationFrame when canvas is offscreen
 *   - rAF + observer both cancelled on unmount (no leaks)
 *   - dpr-aware canvas sizing
 *
 * Props:
 *   color?    — single color, backward-compatible (wraps in array)
 *   colors?   — array of hex/rgb colors cycled across particles
 *   behavior? — ParticleBehavior (default: "drift")
 *   quantity? — number of particles (default: 30)
 *   size?     — base radius in px (default: 1.5)
 *   className — forwarded to canvas
 */

import { useEffect, useMemo, useRef } from "react";
import { cn } from "@/lib/utils";
import { motionConfig } from "@/lib/motion";
import { useThemeStore } from "@/stores/themeStore";
import type { ParticleBehavior } from "@/lib/cinematicThemes";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface ParticleState {
  x: number;
  y: number;
  vx: number;
  vy: number;
  alpha: number;
  /** Base alpha for pulse behavior */
  baseAlpha: number;
  /** Phase offset for float / pulse (radians) */
  phase: number;
  colorIdx: number;
  size: number;
}

export interface ParticlesProps {
  className?: string;
  quantity?: number;
  /** Multi-color array — particles cycle through these colors */
  colors?: string[];
  /** Single color, backward-compatible. Ignored when colors is provided. */
  color?: string;
  size?: number;
  sizeRange?: readonly [number, number];
  behavior?: ParticleBehavior;
  seed?: number;
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const LOW_END_THRESHOLD = 4; // hardwareConcurrency <= this → reduce quantity

// Pulse max 2 Hz per WCAG 2.3 (photosensitivity) — minimum 500ms full-cycle
const PULSE_MIN_PERIOD_MS = 500;

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function Particles({
  className,
  quantity = 30,
  colors,
  color = "#22c55e",
  size = 1.5,
  sizeRange,
  behavior = "drift",
  seed = 7_137,
}: ParticlesProps) {
  // Reduced motion: OS/browser setting
  const osReducedMotion = motionConfig.prefersReducedMotion();
  // Reduced motion: user store override
  const storeReduceMotion = useThemeStore((s) => s.reduceMotion);

  // Resolve color array
  const colorList: string[] = useMemo(
    () => (colors && colors.length > 0 ? colors : [color]),
    [color, colors],
  );

  if (osReducedMotion || storeReduceMotion) {
    return null;
  }

  return (
    <ParticlesCanvas
      className={className}
      quantity={quantity}
      colors={colorList}
      size={size}
      sizeRange={sizeRange}
      behavior={behavior}
      seed={seed}
    />
  );
}

// ---------------------------------------------------------------------------
// Inner canvas component (only rendered when motion is allowed)
// ---------------------------------------------------------------------------

interface CanvasProps {
  className?: string;
  quantity: number;
  colors: string[];
  size: number;
  sizeRange?: readonly [number, number];
  behavior: ParticleBehavior;
  seed: number;
}

function createSeededRandom(seed: number): () => number {
  let state = seed >>> 0;
  return () => {
    state = (state * 1_664_525 + 1_013_904_223) >>> 0;
    return state / 4_294_967_296;
  };
}

function ParticlesCanvas({
  className,
  quantity,
  colors,
  size,
  sizeRange,
  behavior,
  seed,
}: CanvasProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    // Low-end device: reduce quantity
    const isLowEnd =
      typeof navigator !== "undefined" &&
      navigator.hardwareConcurrency <= LOW_END_THRESHOLD;
    const actualQuantity = isLowEnd ? Math.ceil(quantity * 0.5) : quantity;

    let animationId: number | null = null;
    let isVisible = true;
    const dpr = window.devicePixelRatio || 1;
    const random = createSeededRandom(seed);

    function resize() {
      if (!canvas) return;
      canvas.width = Math.max(1, Math.floor(canvas.offsetWidth * dpr));
      canvas.height = Math.max(1, Math.floor(canvas.offsetHeight * dpr));
      ctx!.setTransform(dpr, 0, 0, dpr, 0, 0);
    }
    resize();

    const w = canvas.offsetWidth;
    const h = canvas.offsetHeight;
    const [minSize, maxSize] = sizeRange ?? [size * 0.8, size * 1.2];

    // Initialise particles
    const particles: ParticleState[] = Array.from(
      { length: actualQuantity },
      (_, i) => ({
        x: random() * w,
        y: behavior === "snow" ? random() * h - h : random() * h,
        vx: (random() - 0.5) * 0.3,
        vy: behavior === "snow"
          ? 0.3 + random() * 0.5
          : (random() - 0.5) * 0.3,
        alpha: random() * 0.5 + 0.2,
        baseAlpha: random() * 0.4 + 0.15,
        phase: random() * Math.PI * 2,
        colorIdx: i % colors.length,
        size: minSize + random() * (maxSize - minSize),
      }),
    );

    let lastTime = performance.now();

    function draw(now: number) {
      if (!canvas || !ctx) return;
      const dt = Math.min(now - lastTime, 50); // cap at 50ms to avoid jumps
      lastTime = now;
      const dtScale = dt / 16.67;
      const t = now / 1000; // seconds

      ctx.clearRect(0, 0, canvas.offsetWidth, canvas.offsetHeight);

      for (const p of particles) {
        switch (behavior) {
          case "drift": {
            p.x += p.vx * dtScale;
            p.y += p.vy * dtScale;
            if (p.x < 0 || p.x > canvas.offsetWidth) p.vx *= -1;
            if (p.y < 0 || p.y > canvas.offsetHeight) p.vy *= -1;
            break;
          }
          case "float": {
            // Gentle sine vertical bobbing, slow lateral drift
            p.x += p.vx * dtScale;
            p.y += Math.sin(t * 0.5 + p.phase) * 0.15 * dtScale;
            if (p.x < 0 || p.x > canvas.offsetWidth) p.vx *= -1;
            break;
          }
          case "pulse": {
            // Opacity oscillation — 2 Hz max = period >= 500ms
            // We use period = max(PULSE_MIN_PERIOD_MS, ...) implicitly via
            // the angular frequency: omega = 2π / period_s
            const omega = (2 * Math.PI) / (PULSE_MIN_PERIOD_MS / 1000);
            p.alpha = p.baseAlpha + 0.3 * (0.5 + 0.5 * Math.sin(omega * t + p.phase));
            break;
          }
          case "snow": {
            p.x += (p.vx + Math.sin(t * 0.3 + p.phase) * 0.1) * dtScale;
            p.y += p.vy * dtScale;
            if (p.y > canvas.offsetHeight + 10) {
              p.y = -10;
              p.x = random() * canvas.offsetWidth;
            }
            if (p.x < 0 || p.x > canvas.offsetWidth) p.vx *= -1;
            break;
          }
        }

        ctx.beginPath();
        ctx.arc(p.x, p.y, p.size, 0, Math.PI * 2);
        ctx.fillStyle = colors[p.colorIdx] ?? colors[0];
        ctx.globalAlpha = Math.max(0.02, Math.min(1, p.alpha));
        ctx.fill();
      }

      ctx.globalAlpha = 1;

      animationId = null;
      if (isVisible) startAnimation();
    }

    function startAnimation() {
      if (animationId !== null) return;
      animationId = requestAnimationFrame(draw);
    }

    function stopAnimation() {
      if (animationId === null) return;
      cancelAnimationFrame(animationId);
      animationId = null;
    }

    startAnimation();

    // Pause when not visible
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (!entry) return;
        isVisible = entry.isIntersecting;
        if (isVisible) {
          lastTime = performance.now();
          startAnimation();
        } else {
          stopAnimation();
        }
      },
      { threshold: 0 },
    );
    observer.observe(canvas);

    const handleResize = () => {
      resize();
    };
    window.addEventListener("resize", handleResize);

    return () => {
      stopAnimation();
      observer.disconnect();
      window.removeEventListener("resize", handleResize);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [quantity, colors, size, sizeRange?.[0], sizeRange?.[1], behavior, seed]);

  return (
    <canvas
      ref={canvasRef}
      className={cn(
        "pointer-events-none absolute inset-0 h-full w-full",
        className,
      )}
      aria-hidden="true"
    />
  );
}
