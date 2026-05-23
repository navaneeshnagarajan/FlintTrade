/**
 * text-generate-effect.tsx
 * Aceternity UI — Words fade in one by one, ideal for AI response streaming.
 * Adapted: React 19, framer-motion v12, TypeScript strict, no `any`.
 */
import { useEffect } from "react";
import { motion, stagger, useAnimate } from "framer-motion";
import { cn } from "@/lib/utils";

/* ------------------------------------------------------------------ */
/* Types                                                                */
/* ------------------------------------------------------------------ */

interface TextGenerateEffectProps {
  /** The text to animate word-by-word. */
  words: string;
  /** Additional className for the outer wrapper. */
  className?: string;
  /** Word span className override. */
  wordClassName?: string;
  /** Delay between each word (seconds). Default 0.2. */
  staggerDelay?: number;
  /** Render as this element. Default "p". */
  as?: "p" | "h1" | "h2" | "h3" | "span" | "div";
}

/* ------------------------------------------------------------------ */
/* Component                                                            */
/* ------------------------------------------------------------------ */

export function TextGenerateEffect({
  words,
  className,
  wordClassName,
  staggerDelay = 0.2,
  as: Tag = "p",
}: TextGenerateEffectProps) {
  const [scope, animate] = useAnimate();

  const wordArray = words.split(" ");

  useEffect(() => {
    void animate(
      "span",
      {
        opacity: 1,
        filter: "blur(0px)",
      },
      {
        duration: 0.4,
        delay: stagger(staggerDelay),
      },
    );
  }, [animate, staggerDelay]);

  return (
    <div ref={scope} className={cn("font-sans", className)}>
      <Tag>
        {wordArray.map((word, i) => (
          <motion.span
            key={`${word}-${i}`}
            className={cn(
              "mr-1 inline-block opacity-0",
              "text-text-primary",
              wordClassName,
            )}
            style={{ filter: "blur(4px)" }}
          >
            {word}
          </motion.span>
        ))}
      </Tag>
    </div>
  );
}
