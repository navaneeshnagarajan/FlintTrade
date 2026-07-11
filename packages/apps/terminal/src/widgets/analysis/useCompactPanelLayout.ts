import { useLayoutEffect, useRef, useState } from "react";

const COMPACT_PANEL_MAX_WIDTH = 520;
const COMPACT_PANEL_MAX_HEIGHT = 160;

export function useCompactPanelLayout<T extends HTMLElement>() {
  const panelRef = useRef<T>(null);
  const [isCompact, setIsCompact] = useState(false);

  useLayoutEffect(() => {
    const panel = panelRef.current;
    if (!panel) return;

    const updateLayout = (width: number, height: number) => {
      if (width <= 0 || height <= 0) return;
      setIsCompact(
        width <= COMPACT_PANEL_MAX_WIDTH || height <= COMPACT_PANEL_MAX_HEIGHT,
      );
    };

    const initialRect = panel.getBoundingClientRect();
    updateLayout(initialRect.width, initialRect.height);

    const observer = new ResizeObserver(([entry]) => {
      if (!entry) return;
      updateLayout(entry.contentRect.width, entry.contentRect.height);
    });
    observer.observe(panel);
    return () => observer.disconnect();
  }, []);

  return { isCompact, panelRef };
}
