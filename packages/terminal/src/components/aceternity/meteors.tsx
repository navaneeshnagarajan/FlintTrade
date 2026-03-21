import { useMemo } from "react";
import { cn } from "@/lib/utils";

interface MeteorData {
  id: number;
  left: string;
  delay: string;
  duration: string;
}

interface MeteorsProps {
  number?: number;
  className?: string;
}

export function Meteors({ number = 12, className }: MeteorsProps) {
  // Memoize so values are stable across re-renders (Math.random is side-effectful)
  const meteors = useMemo<MeteorData[]>(
    () =>
      Array.from({ length: number }, (_, i) => ({
        id: i,
        left: `${Math.random() * 100}%`,
        delay: `${Math.random() * 3}s`,
        duration: `${Math.random() * 2 + 2}s`,
      })),
    [number],
  );

  return (
    <>
      {/* Keyframe definition — injected once per mount */}
      <style>{`
        @keyframes meteor {
          0%   { transform: rotate(215deg) translateX(0);   opacity: 1; }
          70%  { opacity: 1; }
          100% { transform: rotate(215deg) translateX(-500px); opacity: 0; }
        }
      `}</style>

      <div
        className={cn(
          "pointer-events-none absolute inset-0 overflow-hidden",
          className,
        )}
        aria-hidden="true"
      >
        {meteors.map((m) => (
          <span
            key={m.id}
            className="absolute top-0 h-0.5 w-0.5 rounded-full bg-profit shadow-[0_0_0_1px_rgba(34,197,94,0.1)]"
            style={{
              left: m.left,
              animationDelay: m.delay,
              animation: `meteor ${m.duration} linear infinite`,
            }}
          >
            {/* Tail */}
            <span className="absolute top-1/2 -z-10 h-px w-12 -translate-y-1/2 bg-gradient-to-r from-profit/60 to-transparent" />
          </span>
        ))}
      </div>
    </>
  );
}
