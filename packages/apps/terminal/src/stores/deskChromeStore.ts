import { create } from "zustand";

interface DeskChromeStore {
  toolsExpanded: boolean;
  setToolsExpanded: (expanded: boolean) => void;
}

export const useDeskChromeStore = create<DeskChromeStore>((set) => ({
  toolsExpanded: false,
  setToolsExpanded: (toolsExpanded) => set({ toolsExpanded }),
}));
