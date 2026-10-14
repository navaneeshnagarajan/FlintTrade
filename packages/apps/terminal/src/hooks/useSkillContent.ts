import { widgetCatalog } from "@/layout/widgetFactory";

export type TooltipLevel = "simple" | "detailed" | "expert";
export interface SkillContent {
  availableWidgets: string[];
  availableTools: string[];
  showAdvanced: boolean;
  tooltipLevel: TooltipLevel;
  defaultPreset: string;
}
const content: SkillContent = {
  availableWidgets: widgetCatalog.map(widget => widget.id),
  availableTools: ["trade-journal", "settings"],
  showAdvanced: true,
  tooltipLevel: "detailed",
  defaultPreset: "market-watch",
};
/** Legacy presentation interface; app purpose, never experience, filters tools. */
export function useSkillContent(): SkillContent { return content; }
