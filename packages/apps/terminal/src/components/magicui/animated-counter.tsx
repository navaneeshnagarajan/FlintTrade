/**
 * AnimatedCounter.tsx
 *
 * Spring-animated numeric counter using Framer Motion.
 *
 * Accessibility:
 *   - Visual span is aria-hidden (screen readers don't track intermediate values)
 *   - sr-only span shows the final formatted value for screen readers
 *
 * Reduced motion:
 *   - When prefers-reduced-motion OR useInView triggers, shows final value
 *     immediately without spring animation
 *
 * Play-once per unique key:
 *   - A ref tracks whether the animation has already played for the current
 *     `value`. Once played, won't re-animate on re-render unless value changes.
 */

import { useEffect, useRef, useState } from "react";
import { motion, useSpring, useTransform, useInView } from "framer-motion";
import { motionConfig } from "@/lib/motion";

interface AnimatedCounterProps {
  value: number;
  direction?: "up" | "down";
  className?: string;
  formatter?: (value: number) => string;
  duration?: number;
}

export function AnimatedCounter({
  value,
  direction = "up",
  className,
  formatter,
  duration = 1.5,
}: AnimatedCounterProps) {
  const ref = useRef<HTMLSpanElement>(null);
  const isInView = useInView(ref, { once: true, margin: "-100px" });

  const reducedMotion = motionConfig.prefersReducedMotion();

  // Track the last value we started the animation for (play-once per value)
  const playedValueRef = useRef<number | null>(null);

  // Format helper
  const format = (v: number): string =>
    formatter ? formatter(Math.round(v)) : Math.round(v).toLocaleString("en-IN");

  // If reduced motion: show final value immediately, no spring
  const spring = useSpring(
    reducedMotion
      ? value
      : direction === "down"
      ? value
      : 0,
    {
      bounce: 0,
      duration: reducedMotion ? 0 : duration * 1000,
    },
  );

  const display = useTransform(spring, (v) => format(v));

  const [displayValue, setDisplayValue] = useState<string>(
    reducedMotion ? format(value) : format(direction === "down" ? value : 0),
  );

  // Start animation when in view, and only once per unique value
  useEffect(() => {
    if (reducedMotion) {
      setDisplayValue(format(value));
      return;
    }
    if (isInView && playedValueRef.current !== value) {
      playedValueRef.current = value;
      spring.set(direction === "down" ? 0 : value);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [spring, value, direction, isInView, reducedMotion]);

  // Keep displayValue in sync with spring
  useEffect(() => {
    return display.on("change", (v) => setDisplayValue(v));
  }, [display]);

  // When reduced motion, keep displayValue updated immediately on value change
  useEffect(() => {
    if (reducedMotion) {
      setDisplayValue(format(value));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value, reducedMotion]);

  return (
    <span ref={ref} className={className}>
      {/* Visual span — hidden from screen readers, shows animation */}
      <motion.span aria-hidden="true">{displayValue}</motion.span>
      {/* sr-only span — shows final value for screen readers */}
      <span className="sr-only">
        {formatter ? formatter(value) : value.toLocaleString("en-IN")}
      </span>
    </span>
  );
}
