import { useEffect, useRef } from "react";
import { useQueryClient, type QueryKey } from "@tanstack/react-query";

/**
 * Start polling again when a hidden tab becomes visible.
 *
 * A refetch interval callback that returns false while the document is
 * hidden makes TanStack drop the timer. A query update in that state
 * (an order notification, for example) does not put the timer back,
 * and window-focus refetch is off. Becoming visible invalidates once,
 * which fetches and lets the interval arm again.
 */
export function useRearmPollingWhenVisible(
  queryKey: QueryKey,
  enabled: boolean | (() => boolean),
): void {
  const queryClient = useQueryClient();
  const keyRef = useRef(queryKey);
  keyRef.current = queryKey;
  const enabledRef = useRef(enabled);
  enabledRef.current = enabled;

  useEffect(() => {
    const onVisibility = () => {
      if (document.hidden) return;
      const active = enabledRef.current;
      if (typeof active === "function" ? !active() : !active) return;
      void queryClient.invalidateQueries({ queryKey: keyRef.current, exact: true });
    };
    document.addEventListener("visibilitychange", onVisibility);
    return () => document.removeEventListener("visibilitychange", onVisibility);
  }, [queryClient]);
}
