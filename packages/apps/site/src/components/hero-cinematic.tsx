'use client';

/**
 * HeroCinematic — backdrop parity with the terminal's WelcomeRoute.
 *
 * Ports the terminal's CinematicBackdrop: three canvas particle layers
 * (drift / pulse / float, same seeds, quantities and opacities) plus the
 * seeded Meteors field (18 streaks). Colours come from the site theme
 * variables so dark and light modes match the app's Graphite theme.
 */

import { useTheme } from 'next-themes';
import { useEffect, useMemo, useRef, useState } from 'react';

type ParticleBehavior = 'drift' | 'float' | 'pulse';

interface ParticleState {
  x: number;
  y: number;
  vx: number;
  vy: number;
  alpha: number;
  baseAlpha: number;
  phase: number;
  colorIdx: number;
  size: number;
}

/** Same LCG as the terminal components — keeps layouts deterministic. */
function createSeededRandom(seed: number): () => number {
  let state = seed >>> 0;
  return () => {
    state = (state * 1_664_525 + 1_013_904_223) >>> 0;
    return state / 4_294_967_296;
  };
}

function usePrefersReducedMotion(): boolean {
  const [reduced, setReduced] = useState(false);
  useEffect(() => {
    const query = window.matchMedia('(prefers-reduced-motion: reduce)');
    setReduced(query.matches);
    const onChange = (event: MediaQueryListEvent) => setReduced(event.matches);
    query.addEventListener('change', onChange);
    return () => query.removeEventListener('change', onChange);
  }, []);
  return reduced;
}

// WebGL pilot coexistence hook (fail-open): pause Canvas2D rAF when ft-scroll-world-on, resume on fallback
  useEffect(() => {
    const onFallback = () => {
      // Resume particles if WebGL failed or disabled
      if (animationId) {
        cancelAnimationFrame(animationId);
        animationId = null;
      }
      // Restart the particle layers if not reduced
      if (!reduced) {
        // Re-trigger by state or simple restart flag
        window.dispatchEvent(new CustomEvent("hero-cinematic-resume"));
      }
    };
    window.addEventListener("ft-scroll-world-fallback", onFallback);
    return () => window.removeEventListener("ft-scroll-world-fallback", onFallback);
  }, [reduced]);


interface ParticleLayerProps {
  quantity: number;
  colors: string[];
  sizeRange: readonly [number, number];
  behavior: ParticleBehavior;
  seed: number;
  opacity: number;
}

const PULSE_MIN_PERIOD_MS = 500;

function ParticleLayer({ quantity, colors, sizeRange, behavior, seed, opacity }: ParticleLayerProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const isLowEnd = typeof navigator !== 'undefined' && navigator.hardwareConcurrency <= 4;
    const actualQuantity = isLowEnd ? Math.ceil(quantity * 0.5) : quantity;

    let animationId: number | null = null;
    let isVisible = true;
    const dpr = window.devicePixelRatio || 1;
    const random = createSeededRandom(seed);

    function resize() {
      if (!canvas || !ctx) return;
      canvas.width = Math.max(1, Math.floor(canvas.offsetWidth * dpr));
      canvas.height = Math.max(1, Math.floor(canvas.offsetHeight * dpr));
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    }
    resize();

    const w = canvas.offsetWidth;
    const h = canvas.offsetHeight;
    const [minSize, maxSize] = sizeRange;

    const particles: ParticleState[] = Array.from({ length: actualQuantity }, (_, i) => ({
      x: random() * w,
      y: random() * h,
      vx: (random() - 0.5) * 0.3,
      vy: (random() - 0.5) * 0.3,
      alpha: random() * 0.5 + 0.2,
      baseAlpha: random() * 0.4 + 0.15,
      phase: random() * Math.PI * 2,
      colorIdx: i % colors.length,
      size: minSize + random() * (maxSize - minSize),
    }));

    let lastTime = performance.now();

    function draw(now: number) {
      if (!canvas || !ctx) return;
      const dt = Math.min(now - lastTime, 50);
      lastTime = now;
      const dtScale = dt / 16.67;
      const t = now / 1000;

      ctx.clearRect(0, 0, canvas.offsetWidth, canvas.offsetHeight);

      for (const p of particles) {
        switch (behavior) {
          case 'drift': {
            p.x += p.vx * dtScale;
            p.y += p.vy * dtScale;
            if (p.x < 0 || p.x > canvas.offsetWidth) p.vx *= -1;
            if (p.y < 0 || p.y > canvas.offsetHeight) p.vy *= -1;
            break;
          }
          case 'float': {
            p.x += p.vx * dtScale;
            p.y += Math.sin(t * 0.5 + p.phase) * 0.15 * dtScale;
            if (p.x < 0 || p.x > canvas.offsetWidth) p.vx *= -1;
            break;
          }
          case 'pulse': {
            const omega = (2 * Math.PI) / (PULSE_MIN_PERIOD_MS / 1000);
            p.alpha = p.baseAlpha + 0.3 * (0.5 + 0.5 * Math.sin(omega * t + p.phase));
            break;
          }
        }

        ctx.beginPath();
        ctx.arc(p.x, p.y, p.size, 0, Math.PI * 2);
        ctx.fillStyle = colors[p.colorIdx] ?? colors[0] ?? '#22c55e';
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

    const handleResize = () => resize();
    window.addEventListener('resize', handleResize);

    return () => {
      stopAnimation();
      observer.disconnect();
      window.removeEventListener('resize', handleResize);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [quantity, colors.join(','), sizeRange[0], sizeRange[1], behavior, seed]);

  return <canvas ref={canvasRef} className="site-particles" style={{ opacity }} aria-hidden="true" />;
}

interface MeteorData {
  id: number;
  left: string;
  delay: string;
  duration: string;
}

function MeteorField({ number = 18, seed = 8_021 }: { number?: number; seed?: number }) {
  const meteors = useMemo<MeteorData[]>(() => {
    const random = createSeededRandom(seed);
    return Array.from({ length: number }, (_, i) => ({
      id: i,
      left: `${random() * 100}%`,
      delay: `${random() * 3}s`,
      duration: `${random() * 2 + 2}s`,
    }));
  }, [number, seed]);

  return (
    <>
      {meteors.map((m) => (
        <span
          key={m.id}
          className="site-meteor"
          style={{ left: m.left, animationDelay: m.delay, animationDuration: m.duration }}
        />
      ))}
    </>
  );
}

// Per-mode drift palettes mirroring the Graphite theme in the terminal's
// cinematicThemes.ts. Constants (rather than reading the CSS variables)
// because next-themes flips the html class in an effect AFTER consumers
// render — a getComputedStyle read here would lag one toggle behind.
const DRIFT_COLORS: Record<string, string[]> = {
  dark: ['#22c55e', '#86efac', '#38bdf8'],
  light: ['#16a34a', '#22c55e', '#4ade80'],
};

export function HeroCinematic() {
  const reducedMotion = usePrefersReducedMotion();
  const { resolvedTheme } = useTheme();
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);

  const driftColors = useMemo(
    () => DRIFT_COLORS[resolvedTheme === 'light' ? 'light' : 'dark'] ?? DRIFT_COLORS.dark,
    [resolvedTheme],
  );

  if (!mounted || reducedMotion) return null;

  return (
    <>
      {/* Same three layers as the terminal CinematicBackdrop. */}
      <ParticleLayer quantity={110} colors={driftColors} sizeRange={[0.8, 2.2]} behavior="drift" seed={19_841} opacity={0.45} />
      <ParticleLayer quantity={36} colors={['#ffffff']} sizeRange={[1.1, 2.8]} behavior="pulse" seed={7_721} opacity={0.25} />
      <ParticleLayer quantity={42} colors={['#22c55e', '#38bdf8', '#a3e635']} sizeRange={[0.4, 1.3]} behavior="float" seed={3_109} opacity={0.3} />
      <MeteorField number={18} seed={8_021} />
    </>
  );
}
