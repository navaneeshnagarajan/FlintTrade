/**
 * CinematicLayout.tsx
 *
 * Two-tier wrapper for route/section backgrounds:
 *
 *   "cinematic" mode — full visual atmosphere:
 *     - Particles rendered (colors from --particle-primary/secondary/tertiary)
 *     - Ambient radial glow (color/opacity/radius from --glow-* CSS vars)
 *     - Themed background
 *
 *   "focused" mode — clean, distraction-free:
 *     - Themed background only
 *     - No particles, no glow
 *
 * Automatic downgrade to "focused" when:
 *   1. prefers-reduced-motion (OS/browser)
 *   2. themeStore.reduceMotion (user override)
 *   3. navigator.hardwareConcurrency <= 4 (low-end device)
 *
 * Usage:
 *   <CinematicLayout mode="cinematic">
 *     <YourContent />
 *   </CinematicLayout>
 */

import * as React from "react";
import { useMemo } from "react";
import { cn } from "@/lib/utils";
import { motionConfig } from "@/lib/motion";
import { useThemeStore } from "@/stores/themeStore";
import { Particles } from "@/components/magicui/particles";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface CinematicLayoutProps {
  mode: "cinematic" | "focused";
  children: React.ReactNode;
  className?: string;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function cssVar(name: string, fallback = ""): string {
  if (typeof window === "undefined") return fallback;
  return (
    getComputedStyle(document.documentElement).getPropertyValue(name).trim() ||
    fallback
  );
}

function isLowEndDevice(): boolean {
  if (typeof navigator === "undefined") return false;
  return navigator.hardwareConcurrency <= 4;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function CinematicLayout({
  mode,
  children,
  className,
}: CinematicLayoutProps) {
  const reduceMotionStore = useThemeStore((s) => s.reduceMotion);

  // Check all downgrade conditions
  const osReducedMotion = motionConfig.prefersReducedMotion();
  const shouldDowngrade =
    osReducedMotion || reduceMotionStore || isLowEndDevice();

  // Effective mode after downgrade
  const effectiveMode: "cinematic" | "focused" =
    mode === "cinematic" && !shouldDowngrade ? "cinematic" : "focused";

  // Read particle colors from CSS vars (only used in cinematic mode)
  const particleColors = useMemo(() => {
    if (effectiveMode !== "cinematic") return [];
    const primary = cssVar("--particle-primary", "#22c55e");
    const secondary = cssVar("--particle-secondary", "#6366f1");
    const tertiary = cssVar("--particle-tertiary", "#06b6d4");
    return [primary, secondary, tertiary].filter(Boolean);
  }, [effectiveMode]);

  // Ambient glow style (only used in cinematic mode)
  const glowStyle = useMemo<React.CSSProperties>(() => {
    if (effectiveMode !== "cinematic") return {};
    const color = cssVar("--glow-color", "rgba(34,197,94,0.12)");
    const opacity = parseFloat(cssVar("--glow-opacity", "0.15")) || 0.15;
    const radius = cssVar("--glow-radius", "60%");
    return {
      backgroundImage: `radial-gradient(ellipse ${radius} ${radius} at 50% 0%, ${color} 0%, transparent 70%)`,
      opacity,
    };
  }, [effectiveMode]);

  return (
    <div className={cn("relative w-full h-full overflow-hidden", className)}>
      {/* Ambient glow overlay (cinematic only) */}
      {effectiveMode === "cinematic" && (
        <div
          className="absolute inset-0 pointer-events-none z-0"
          style={glowStyle}
          aria-hidden="true"
        />
      )}

      {/* Particles (cinematic only) */}
      {effectiveMode === "cinematic" && particleColors.length > 0 && (
        <Particles
          colors={particleColors}
          quantity={20}
          behavior="drift"
          className="z-0"
        />
      )}

      {/* Content — always above particles/glow */}
      <div className="relative z-10 w-full h-full">
        {children}
      </div>
    </div>
  );
}

export default CinematicLayout;
