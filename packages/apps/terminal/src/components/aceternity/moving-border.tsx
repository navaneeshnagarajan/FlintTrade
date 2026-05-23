/**
 * moving-border.tsx
 * Aceternity UI — Animated gradient border for CTA buttons / highlighted cards.
 * Adapted: React 19, framer-motion v12, TypeScript strict, no `any`.
 */
import { useRef, type ComponentPropsWithoutRef, type ReactNode } from "react";
import { motion, useAnimationFrame, useMotionTemplate, useMotionValue, useTransform } from "framer-motion";
import { cn } from "@/lib/utils";

/* ------------------------------------------------------------------ */
/* Main export — button variant                                         */
/* ------------------------------------------------------------------ */

type MovingBorderButtonProps = ComponentPropsWithoutRef<"button"> & {
  /** Duration of one full rotation in ms. Default 3000. */
  duration?: number;
  rx?: string;
  ry?: string;
  containerClassName?: string;
  borderClassName?: string;
};

export function MovingBorder({
  children,
  duration = 3000,
  rx = "30%",
  ry = "30%",
  containerClassName,
  borderClassName,
  className,
  ...rest
}: MovingBorderButtonProps) {
  return (
    <button
      className={cn(
        "relative h-10 overflow-hidden rounded-glass-control p-px text-sm",
        containerClassName,
      )}
      {...rest}
    >
      {/* Rotating border shimmer */}
      <div className="absolute inset-0" style={{ borderRadius: "inherit" }}>
        <MovingBorderSVG duration={duration} rx={rx} ry={ry} className={borderClassName} />
      </div>
      {/* Content */}
      <div
        className={cn(
          "relative flex h-full w-full items-center justify-center rounded-[calc(var(--glass-radius-control)-1px)]",
          "bg-glass-chrome text-sm antialiased",
          className,
        )}
      >
        {children}
      </div>
    </button>
  );
}

/* ------------------------------------------------------------------ */
/* Div / container variant (for wrapping cards etc.)                   */
/* ------------------------------------------------------------------ */

type MovingBorderDivProps = ComponentPropsWithoutRef<"div"> & {
  duration?: number;
  rx?: string;
  ry?: string;
  containerClassName?: string;
  borderClassName?: string;
  children?: ReactNode;
};

export function MovingBorderDiv({
  children,
  duration = 3000,
  rx = "30%",
  ry = "30%",
  containerClassName,
  borderClassName,
  className,
  ...rest
}: MovingBorderDivProps) {
  return (
    <div
      className={cn(
        "relative overflow-hidden rounded-glass-card p-px",
        containerClassName,
      )}
      {...rest}
    >
      <div className="absolute inset-0" style={{ borderRadius: "inherit" }}>
        <MovingBorderSVG duration={duration} rx={rx} ry={ry} className={borderClassName} />
      </div>
      <div
        className={cn(
          "relative rounded-[calc(var(--glass-radius-card)-1px)]",
          "bg-glass-chrome",
          className,
        )}
      >
        {children}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Internal SVG rotating gradient                                       */
/* ------------------------------------------------------------------ */

interface MovingBorderSVGProps {
  duration?: number;
  rx?: string;
  ry?: string;
  className?: string;
}

function MovingBorderSVG({ duration = 3000, rx = "30%", ry = "30%", className }: MovingBorderSVGProps) {
  const pathRef = useRef<SVGRectElement>(null);
  const progress = useMotionValue<number>(0);

  useAnimationFrame((time) => {
    const length = pathRef.current?.getTotalLength?.();
    if (length) {
      const pxPerMs = length / duration;
      progress.set((time * pxPerMs) % length);
    }
  });

  const x = useTransform(progress, (val) => pathRef.current?.getPointAtLength(val)?.x ?? 0);
  const y = useTransform(progress, (val) => pathRef.current?.getPointAtLength(val)?.y ?? 0);

  const transform = useMotionTemplate`translateX(${x}px) translateY(${y}px) translateX(-50%) translateY(-50%)`;

  return (
    <>
      <svg
        xmlns="http://www.w3.org/2000/svg"
        preserveAspectRatio="none"
        className="absolute inset-0 h-full w-full"
        aria-hidden="true"
      >
        <rect
          fill="none"
          width="100%"
          height="100%"
          rx={rx}
          ry={ry}
          ref={pathRef}
        />
      </svg>
      <motion.div
        style={{
          position: "absolute",
          top: 0,
          left: 0,
          display: "inline-block",
          transform,
        }}
      >
        <div
          className={cn(
            "h-20 w-20 rounded-full opacity-[0.8] blur-[20px]",
            "bg-[radial-gradient(circle_at_center,theme(colors.blue.500),transparent_60%)]",
            className,
          )}
        />
      </motion.div>
    </>
  );
}
