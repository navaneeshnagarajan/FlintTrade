import { useEffect, useState } from "react";
import {
  resolveDockMode,
  showFullToolRibbon,
  showTickerChrome,
  usesCompactProgressiveDisclosure,
  type SidebarDisplayMode,
} from "@/lib/tradeDeskDensity";
import { useDeskChromeStore } from "@/stores/deskChromeStore";
import { useSettingsStore } from "@/stores/settingsStore";

function readWidth(): number {
  if (typeof window === "undefined") return 0;
  return window.innerWidth;
}

export function useViewportWidth(): number {
  const [width, setWidth] = useState(readWidth);

  useEffect(() => {
    function onResize() {
      setWidth(readWidth());
    }
    onResize();
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);

  return width;
}

export function useDeskDensityChrome(): {
  density: "compact" | "comfortable";
  viewportWidth: number;
  progressive: boolean;
  toolsExpanded: boolean;
  setToolsExpanded: (expanded: boolean) => void;
  showTicker: boolean;
  showToolRibbon: boolean;
  dockModeFor: (stored: SidebarDisplayMode) => SidebarDisplayMode;
} {
  const density = useSettingsStore((s) => s.density);
  const viewportWidth = useViewportWidth();
  const toolsExpanded = useDeskChromeStore((s) => s.toolsExpanded);
  const setToolsExpanded = useDeskChromeStore((s) => s.setToolsExpanded);
  const progressive = usesCompactProgressiveDisclosure(density, viewportWidth);

  return {
    density,
    viewportWidth,
    progressive,
    toolsExpanded,
    setToolsExpanded,
    showTicker: showTickerChrome(density, viewportWidth, toolsExpanded),
    showToolRibbon: showFullToolRibbon(density, viewportWidth, toolsExpanded),
    dockModeFor: (stored) => resolveDockMode(density, stored, viewportWidth),
  };
}
