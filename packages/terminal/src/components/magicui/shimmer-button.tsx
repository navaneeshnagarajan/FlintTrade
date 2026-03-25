/**
 * ShimmerButton.tsx
 *
 * Button with a spinning conic-gradient shimmer ring.
 *
 * Theming:
 *   - shimmerColor prop defaults to CSS var --shimmer-color when available,
 *     otherwise falls back to the hardcoded default.
 *
 * Reduced motion:
 *   - When prefers-reduced-motion is set, the spinning animation is replaced
 *     with a static accent border (no animation, no gradient spin).
 */

import { type ReactNode } from "react";
import { cn } from "@/lib/utils";
import { motionConfig } from "@/lib/motion";

interface ShimmerButtonProps {
  children: ReactNode;
  className?: string;
  shimmerColor?: string;
  shimmerSize?: string;
  onClick?: () => void;
  type?: "button" | "submit" | "reset";
  disabled?: boolean;
}

function getCssVar(name: string, fallback: string): string {
  if (typeof window === "undefined") return fallback;
  const val = getComputedStyle(document.documentElement)
    .getPropertyValue(name)
    .trim();
  return val || fallback;
}

export function ShimmerButton({
  children,
  className,
  shimmerColor,
  shimmerSize = "0.1em",
  onClick,
  type = "button",
  disabled,
}: ShimmerButtonProps) {
  const reducedMotion = motionConfig.prefersReducedMotion();

  // Resolve shimmer color: prop > CSS var > hardcoded default
  const resolvedColor =
    shimmerColor ??
    getCssVar("--shimmer-color", "#22c55e");

  if (reducedMotion) {
    // Static fallback: simple bordered button, no spinning gradient
    return (
      <button
        type={type}
        onClick={onClick}
        disabled={disabled}
        className={cn(
          "relative inline-flex items-center justify-center overflow-hidden rounded-lg px-6 py-2.5",
          "bg-surface-card border-2 text-text-primary font-medium text-sm",
          "transition-opacity duration-100",
          "disabled:opacity-50 disabled:cursor-not-allowed",
          className,
        )}
        style={{ borderColor: resolvedColor }}
      >
        <span className="relative z-10 flex items-center gap-2">{children}</span>
      </button>
    );
  }

  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled}
      className={cn(
        "group relative inline-flex items-center justify-center overflow-hidden rounded-lg px-6 py-2.5",
        "bg-surface-card border border-border-default text-text-primary font-medium text-sm",
        "transition-all duration-300 hover:shadow-[0_0_20px_rgba(34,197,94,0.3)]",
        "disabled:opacity-50 disabled:cursor-not-allowed",
        className,
      )}
    >
      {/* Spinning conic gradient ring */}
      <span
        className="absolute inset-0 overflow-hidden rounded-lg"
        style={{ padding: shimmerSize }}
        aria-hidden="true"
      >
        <span
          className="absolute inset-[-100%] animate-[spin_3s_linear_infinite]"
          style={{
            background: `conic-gradient(from 90deg at 50% 50%, transparent 0%, ${resolvedColor} 50%, transparent 100%)`,
          }}
        />
      </span>

      {/* Inner fill to hide the gradient except at the border */}
      <span className="absolute inset-px rounded-lg bg-surface-card" aria-hidden="true" />

      {/* Actual content */}
      <span className="relative z-10 flex items-center gap-2">{children}</span>
    </button>
  );
}
