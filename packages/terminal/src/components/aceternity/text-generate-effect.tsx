import { useEffect } from "react";
import { motion, stagger, useAnimate } from "framer-motion";
import { cn } from "@/lib/utils";

interface TextGenerateProps {
  words: string;
  className?: string;
  duration?: number;
}

export function TextGenerateEffect({
  words,
  className,
  duration = 0.5,
}: TextGenerateProps) {
  const [scope, animate] = useAnimate();
  const wordsArray = words ? words.split(" ") : [];

  useEffect(() => {
    if (!wordsArray.length) return;
    void animate(
      "span",
      { opacity: 1, filter: "blur(0px)" },
      { duration, delay: stagger(0.08) },
    );
  // words drives re-animation when the prop changes
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [animate, duration, words]);

  if (!wordsArray.length) return null;

  return (
    <motion.div ref={scope} className={cn("font-heading", className)}>
      {wordsArray.map((word, i) => (
        <motion.span
          // word alone is not guaranteed unique (e.g. "the the"), use index
          key={`${word}-${i}`}
          className="opacity-0"
          style={{ filter: "blur(10px)" }}
        >
          {word}{" "}
        </motion.span>
      ))}
    </motion.div>
  );
}
