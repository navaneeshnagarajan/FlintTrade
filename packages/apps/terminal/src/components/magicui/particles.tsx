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

import { useEffect, useRef } from "react";
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
  behavior?: ParticleBehavior;
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
  behavior = "drift",
}: ParticlesProps) {
  // Reduced motion: OS/browser setting
  const osReducedMotion = motionConfig.prefersReducedMotion();
  // Reduced motion: user store override
  const storeReduceMotion = useThemeStore((s) => s.reduceMotion);

  if (osReducedMotion || storeReduceMotion) {
    return null;
  }

  // Resolve color array
  const colorList: string[] =
    colors && colors.length > 0 ? colors : [color];

  return (
    <ParticlesCanvas
      className={className}
      quantity={quantity}
      colors={colorList}
      size={size}
      behavior={behavior}
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
  behavior: ParticleBehavior;
}

function ParticlesCanvas({ className, quantity, colors, size, behavior }: CanvasProps) {
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

    let animationId: number;
    let isVisible = true;
    const dpr = window.devicePixelRatio || 1;

    function resize() {
      if (!canvas) return;
      canvas.width = canvas.offsetWidth * dpr;
      canvas.height = canvas.offsetHeight * dpr;
      ctx!.scale(dpr, dpr);
    }
    resize();

    const w = canvas.offsetWidth;
    const h = canvas.offsetHeight;

    // Initialise particles
    const particles: ParticleState[] = Array.from(
      { length: actualQuantity },
      (_, i) => ({
        x: Math.random() * w,
        y: behavior === "snow" ? Math.random() * h - h : Math.random() * h,
        vx: (Math.random() - 0.5) * 0.3,
        vy: behavior === "snow"
          ? 0.3 + Math.random() * 0.5
          : (Math.random() - 0.5) * 0.3,
        alpha: Math.random() * 0.5 + 0.2,
        baseAlpha: Math.random() * 0.4 + 0.15,
        phase: Math.random() * Math.PI * 2,
        colorIdx: i % colors.length,
        size: size * (0.8 + Math.random() * 0.4),
      }),
    );

    let lastTime = performance.now();

    function draw(now: number) {
      if (!canvas || !ctx) return;
      const dt = Math.min(now - lastTime, 50); // cap at 50ms to avoid jumps
      lastTime = now;
      const t = now / 1000; // seconds

      ctx.clearRect(0, 0, canvas.offsetWidth, canvas.offsetHeight);

      for (const p of particles) {
        switch (behavior) {
          case "drift": {
            p.x += p.vx;
            p.y += p.vy;
            if (p.x < 0 || p.x > canvas.offsetWidth) p.vx *= -1;
            if (p.y < 0 || p.y > canvas.offsetHeight) p.vy *= -1;
            break;
          }
          case "float": {
            // Gentle sine vertical bobbing, slow lateral drift
            p.x += p.vx;
            p.y = p.y + Math.sin(t * 0.5 + p.phase) * 0.15;
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
            p.x += p.vx + Math.sin(t * 0.3 + p.phase) * 0.1;
            p.y += p.vy * (dt / 16); // normalize to ~60fps
            if (p.y > canvas.offsetHeight + 10) {
              p.y = -10;
              p.x = Math.random() * canvas.offsetWidth;
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

      if (isVisible) {
        animationId = requestAnimationFrame(draw);
      }
    }

    animationId = requestAnimationFrame(draw);

    // Pause when not visible
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (!entry) return;
        isVisible = entry.isIntersecting;
        if (isVisible) {
          lastTime = performance.now();
          animationId = requestAnimationFrame(draw);
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
      cancelAnimationFrame(animationId);
      observer.disconnect();
      window.removeEventListener("resize", handleResize);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [quantity, colors, size, behavior]);

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
