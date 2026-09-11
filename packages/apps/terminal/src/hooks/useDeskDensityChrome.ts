import { useEffect, useState } from "react";
import { useLocation } from "react-router";
import {
  applyDeskDensitySelection,
  defaultTradePresetId,
  isTradePath,
  resolveDockMode,
  showFullToolRibbon,
  showTickerChrome,
  usesCompactProgressiveDisclosure,
  type SidebarDisplayMode,
  type UiDensity,
} from "@/lib/tradeDeskDensity";
import { applyDensityToDocument } from "@/lib/applyDensity";
import { buildBeginnerCore, buildCompactDesk, buildPresetJsonById } from "@/layout/workspacePresets";
import { useDeskChromeStore } from "@/stores/deskChromeStore";
import { useLayoutStore } from "@/stores/layoutStore";
import { useSettingsStore } from "@/stores/settingsStore";
import { useSkillStore } from "@/stores/skillStore";

function readWidth(): number {
  if (typeof window === "undefined") return 0;
  return window.innerWidth;
}

/**
 * Persist density, mirror it onto the document, and apply Compact /
 * Comfortable Trade disclosure. Compact always starts with Watchlist &
 * tools collapsed on a desk Trade viewport.
 */
export function selectDeskDensity(density: UiDensity): void {
  useSettingsStore.getState().setDensity(density);
  applyDensityToDocument(density);
  const width = typeof window === "undefined" ? 0 : window.innerWidth;
  const onTrade = typeof window !== "undefined" && isTradePath(window.location.pathname);
  const skill = useSkillStore.getState().getEffectiveLevel("trade");
  applyDeskDensitySelection(density, {
    viewportWidth: width,
    onTrade,
    layout: useLayoutStore.getState().workspaceApi,
    loadCompactDesk: buildCompactDesk,
    loadComfortableDesk: () =>
      buildPresetJsonById(defaultTradePresetId(skill, "comfortable", width, false, onTrade))
      ?? buildBeginnerCore(),
    setToolsExpanded: (expanded) => useDeskChromeStore.getState().setToolsExpanded(expanded),
  });
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
  const pathname = useLocation().pathname;
  const onTrade = isTradePath(pathname);
  const progressive = usesCompactProgressiveDisclosure(density, viewportWidth, onTrade);

  return {
    density,
    viewportWidth,
    progressive,
    toolsExpanded,
    setToolsExpanded,
    showTicker: showTickerChrome(density, viewportWidth, toolsExpanded, onTrade),
    showToolRibbon: showFullToolRibbon(density, viewportWidth, toolsExpanded, onTrade),
    dockModeFor: (stored) => resolveDockMode(density, stored, viewportWidth, onTrade),
  };
}
