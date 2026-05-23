/**
 * useCountdown — returns a formatted countdown string to a Unix ms timestamp.
 * Updates every second. Returns "Now" once the target is reached.
 */
import { useState, useEffect } from "react";

export function useCountdown(targetMs: number): string {
  const [label, setLabel] = useState("");

  useEffect(() => {
    function compute() {
      const diff = targetMs - Date.now();
      if (diff <= 0) {
        setLabel("Now");
        return;
      }
      const h = Math.floor(diff / 3_600_000);
      const m = Math.floor((diff % 3_600_000) / 60_000);
      const s = Math.floor((diff % 60_000) / 1_000);
      setLabel(
        h > 0
          ? `${h}h ${m.toString().padStart(2, "0")}m`
          : `${m}m ${s.toString().padStart(2, "0")}s`,
      );
    }
    compute();
    const id = setInterval(compute, 1_000);
    return () => clearInterval(id);
  }, [targetMs]);

  return label;
}
