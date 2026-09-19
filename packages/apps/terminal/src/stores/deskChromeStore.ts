import { create } from "zustand";

interface DeskChromeStore {
  toolsExpanded: boolean;
  setToolsExpanded: (expanded: boolean) => void;
  /** Skinny-window More can re-show the dedicated ticker strip under TopBar. */
  tickerForcedOnNarrow: boolean;
  setTickerForcedOnNarrow: (forced: boolean) => void;
}

export const useDeskChromeStore = create<DeskChromeStore>((set) => ({
  toolsExpanded: false,
  setToolsExpanded: (toolsExpanded) => set({ toolsExpanded }),
  tickerForcedOnNarrow: false,
  setTickerForcedOnNarrow: (tickerForcedOnNarrow) => set({ tickerForcedOnNarrow }),
}));
