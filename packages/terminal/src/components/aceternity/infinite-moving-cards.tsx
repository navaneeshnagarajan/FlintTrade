/**
 * infinite-moving-cards.tsx
 * Aceternity UI — Infinite loop carousel, ideal for tickers / testimonials.
 * Adapted: React 19, TypeScript strict, no `any`, CSS animation (no JS scroll).
 */
import { useEffect, useRef, useState, type ReactNode } from "react";
import { cn } from "@/lib/utils";

/* ------------------------------------------------------------------ */
/* Types                                                                */
/* ------------------------------------------------------------------ */

export interface MovingCardItem {
  /** Unique key. */
  id: string | number;
  /** Content to render inside the card. */
  content: ReactNode;
}

interface InfiniteMovingCardsProps {
  items: MovingCardItem[];
  /** "left" (default) or "right". */
  direction?: "left" | "right";
  /** "fast" | "normal" | "slow". Default: "normal". */
  speed?: "fast" | "normal" | "slow";
  pauseOnHover?: boolean;
  className?: string;
  itemClassName?: string;
}

/* ------------------------------------------------------------------ */
/* Speed map                                                            */
/* ------------------------------------------------------------------ */

const SPEED_MAP: Record<"fast" | "normal" | "slow", string> = {
  fast: "20s",
  normal: "40s",
  slow: "80s",
};

/* ------------------------------------------------------------------ */
/* Component                                                            */
/* ------------------------------------------------------------------ */

export function InfiniteMovingCards({
  items,
  direction = "left",
  speed = "normal",
  pauseOnHover = true,
  className,
  itemClassName,
}: InfiniteMovingCardsProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const scrollerRef = useRef<HTMLUListElement>(null);
  const [start, setStart] = useState(false);

  useEffect(() => {
    if (!containerRef.current || !scrollerRef.current) return;

    // Duplicate items for seamless loop
    const scrollerContent = Array.from(scrollerRef.current.children);
    scrollerContent.forEach((item) => {
      const clone = item.cloneNode(true);
      scrollerRef.current?.appendChild(clone);
    });

    // Apply CSS custom properties for animation
    containerRef.current.style.setProperty(
      "--animation-duration",
      SPEED_MAP[speed],
    );
    containerRef.current.style.setProperty(
      "--animation-direction",
      direction === "left" ? "forwards" : "reverse",
    );

    setStart(true);
  }, [direction, speed]);

  return (
    <div
      ref={containerRef}
      className={cn(
        "relative z-20 max-w-full overflow-hidden",
        // Edge fade masks
        "[mask-image:linear-gradient(to_right,transparent,white_10%,white_90%,transparent)]",
        className,
      )}
    >
      <ul
        ref={scrollerRef}
        className={cn(
          "flex w-max min-w-full shrink-0 flex-nowrap gap-4 py-2",
          start && "animate-infinite-scroll",
          pauseOnHover && "hover:[animation-play-state:paused]",
        )}
      >
        {items.map((item) => (
          <li
            key={item.id}
            className={cn(
              "relative shrink-0 rounded-glass-inner px-3 py-2",
              "bg-glass-l1 border border-glass-l1 backdrop-glass",
              itemClassName,
            )}
          >
            {item.content}
          </li>
        ))}
      </ul>
      {/* Keyframe injected via style tag — avoids needing to modify global CSS */}
      <style>{`
        @keyframes infinite-scroll {
          from { transform: translateX(0); }
          to   { transform: translateX(calc(-50%)); }
        }
        .animate-infinite-scroll {
          animation: infinite-scroll var(--animation-duration, 40s) linear infinite;
          animation-direction: var(--animation-direction, forwards);
        }
      `}</style>
    </div>
  );
}
