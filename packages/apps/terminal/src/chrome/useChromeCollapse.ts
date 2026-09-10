/**
 * Viewport gates for defensive skinny-window TopBar chrome (FT-MOBILE-002).
 *
 * Desk-first: normal and widescreen stay unchanged. These queries only collapse
 * browser chrome when the window is already too narrow to keep every control
 * on one row.
 */

import { useEffect, useState } from "react";

/** Hide the ticker strip by default under this width. Settings can re-enable. */
export const TICKER_DEFAULT_OFF_MAX_WIDTH = 479;

/** Overflow Workspace and secondary chrome into More at about 390px. */
export const CHROME_COLLAPSE_MAX_WIDTH = 399;

function useMaxWidthMedia(maxWidth: number): boolean {
  const query = `(max-width: ${maxWidth}px)`;
  const [matches, setMatches] = useState(() => {
    if (typeof window === "undefined" || typeof window.matchMedia !== "function") {
      return false;
    }
    return window.matchMedia(query).matches;
  });

  useEffect(() => {
    if (typeof window.matchMedia !== "function") return;
    const mediaQuery = window.matchMedia(query);
    const handleChange = (event: MediaQueryListEvent) => {
      setMatches(event.matches);
    };
    setMatches(mediaQuery.matches);
    mediaQuery.addEventListener("change", handleChange);
    return () => mediaQuery.removeEventListener("change", handleChange);
  }, [query]);

  return matches;
}

export function useChromeCollapse(): {
  hideTickerByDefault: boolean;
  collapseOverflow: boolean;
} {
  const hideTickerByDefault = useMaxWidthMedia(TICKER_DEFAULT_OFF_MAX_WIDTH);
  const collapseOverflow = useMaxWidthMedia(CHROME_COLLAPSE_MAX_WIDTH);
  return { hideTickerByDefault, collapseOverflow };
}
