import { useEffect, useRef, useState } from "react";
import { motion, useSpring, useTransform, useInView } from "framer-motion";

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

  const spring = useSpring(direction === "down" ? value : 0, {
    bounce: 0,
    duration: duration * 1000,
  });

  const display = useTransform(spring, (v) =>
    formatter
      ? formatter(Math.round(v))
      : Math.round(v).toLocaleString("en-IN"),
  );

  const [displayValue, setDisplayValue] = useState(
    formatter
      ? formatter(direction === "down" ? value : 0)
      : "0",
  );

  useEffect(() => {
    if (isInView) spring.set(direction === "down" ? 0 : value);
  }, [spring, value, direction, isInView]);

  useEffect(() => {
    return display.on("change", (v) => setDisplayValue(v));
  }, [display]);

  return (
    <motion.span ref={ref} className={className}>
      {displayValue}
    </motion.span>
  );
}
