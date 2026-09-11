/**
 * useNarrowLayout — observe a container and report phone-width books.
 *
 * Positions and Holdings keep a wide nowrap table on desktop. At about 390px
 * that table clips P&L and P&L% behind a near-invisible scrollbar. Both
 * surfaces switch to stacked cards when the observed width is at or below
 * {@link NARROW_BOOK_MAX_WIDTH}.
 */

import { useLayoutEffect, useRef, useState, type RefObject } from "react";

/** Phone-width threshold. 390px viewports (and equally narrow panels) are narrow. */
export const NARROW_BOOK_MAX_WIDTH = 480;

/**
 * Observe `containerRef` and set `isNarrow` when its content width is at or
 * below `maxWidth`. Zero-width measurements are ignored so jsdom's 0×0 rects
 * do not flip the layout in tests that never fire ResizeObserver.
 */
export function useNarrowLayout<T extends HTMLElement>(
  maxWidth: number = NARROW_BOOK_MAX_WIDTH,
): { isNarrow: boolean; containerRef: RefObject<T | null> } {
  const containerRef = useRef<T>(null);
  const [isNarrow, setIsNarrow] = useState(false);

  useLayoutEffect(() => {
    const el = containerRef.current;
    if (!el || typeof ResizeObserver === "undefined") return;

    const update = (width: number) => {
      if (width <= 0) return;
      setIsNarrow(width <= maxWidth);
    };

    update(el.getBoundingClientRect().width);

    const observer = new ResizeObserver(([entry]) => {
      if (!entry) return;
      update(entry.contentRect.width);
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, [maxWidth]);

  return { isNarrow, containerRef };
}
