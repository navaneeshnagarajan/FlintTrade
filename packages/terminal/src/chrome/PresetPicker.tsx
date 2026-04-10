import {
  Zap,
  Grid3x3,
  Star,
  BarChart3,
  ShieldAlert,
  TrendingUp,
  Sigma,
  Map,
  Bot,
  PieChart,
  Globe,
  Gauge,
  Box,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog";
import { useLayoutStore } from "@/stores/layoutStore";
import { WORKSPACE_PRESETS } from "@/layout/workspacePresets";

// Only the icons actually referenced by presets — keeps tree-shaking effective.
const ICON_MAP: Record<string, LucideIcon> = {
  Zap,
  Grid3x3,
  Star,
  BarChart3,
  ShieldAlert,
  TrendingUp,
  Sigma,
  Map,
  Bot,
  PieChart,
  Globe,
  Gauge,
};

interface PresetPickerProps {
  isOpen: boolean;
  onClose: () => void;
}

/**
 * PresetPicker -- shadcn Dialog listing the 6 built-in workspace presets.
 * Selecting a preset clears the current Dockview canvas and applies the
 * chosen layout immediately. The auto-save listener in TerminalRoute then
 * persists the result to the active workspace tab.
 */
export default function PresetPicker({ isOpen, onClose }: PresetPickerProps) {
  const applyPreset = useLayoutStore((s) => s.applyPreset);

  const handleSelect = (presetId: string) => {
    applyPreset(presetId);
    onClose();
  };

  return (
    <Dialog open={isOpen} onOpenChange={(open) => { if (!open) onClose(); }}>
      <DialogContent className="sm:max-w-3xl max-h-[85vh] flex flex-col bg-surface-card border-border-default p-0 animate-fade-in-scale">
        <DialogHeader className="px-6 pt-5 pb-4 border-b border-border-default shrink-0">
          <DialogTitle className="text-sm font-semibold text-text-primary tracking-wide">
            Choose a Workspace Template
          </DialogTitle>
          <DialogDescription className="text-xs text-text-muted mt-0.5">
            Selecting a template will replace your current layout. Your saved
            workspaces are not affected.
          </DialogDescription>
        </DialogHeader>

        <div className="p-4 grid grid-cols-3 gap-3 overflow-y-auto flex-1 min-h-0">
          {WORKSPACE_PRESETS.map((preset) => {
            const Icon: LucideIcon = ICON_MAP[preset.icon] ?? Box;
            return (
              <button
                key={preset.id}
                onClick={() => handleSelect(preset.id)}
                className="flex items-start gap-3 p-4 rounded-lg border border-border-default hover:border-accent/50 hover:bg-surface-hover transition-colors text-left group"
              >
                <div className="mt-0.5 shrink-0 p-2 rounded-md bg-surface-hover group-hover:bg-accent/10 transition-colors">
                  <Icon
                    size={18}
                    className="text-text-secondary group-hover:text-accent transition-colors"
                  />
                </div>
                <div className="min-w-0">
                  <p className="text-sm font-medium text-text-primary leading-tight">
                    {preset.name}
                  </p>
                  <p className="text-xs text-text-muted mt-1 leading-snug">
                    {preset.description}
                  </p>
                </div>
              </button>
            );
          })}
        </div>
      </DialogContent>
    </Dialog>
  );
}
