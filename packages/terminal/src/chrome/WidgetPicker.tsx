import * as LucideIcons from "lucide-react";
import type { LucideIcon } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { useLayoutStore } from "@/stores/layoutStore";
import { widgetCatalog } from "@/layout/widgetFactory";
import type { WidgetMeta } from "@/types/widgets";

interface WidgetPickerProps {
  isOpen: boolean;
  onClose: () => void;
}

/**
 * WidgetPicker -- shadcn Dialog for adding widgets to the Dockview canvas.
 * Uses dockviewApi from layoutStore to add panels directly.
 */
export default function WidgetPicker({ isOpen, onClose }: WidgetPickerProps) {
  const dockviewApi = useLayoutStore((s) => s.dockviewApi);

  const handleAddWidget = (widget: WidgetMeta) => {
    if (!dockviewApi) return;

    // Generate unique panel id to allow multiple instances
    const panelId = `${widget.id}-${Date.now()}`;
    dockviewApi.addPanel({
      id: panelId,
      component: widget.id,
      title: widget.name,
    });
    onClose();
  };

  // Derive unique ordered category list from the catalog
  const categories: string[] = [];
  for (const w of widgetCatalog) {
    if (!categories.includes(w.category)) categories.push(w.category);
  }

  return (
    <Dialog open={isOpen} onOpenChange={(open) => { if (!open) onClose(); }}>
      <DialogContent className="sm:max-w-[520px] max-h-[80vh] flex flex-col bg-surface-card border-border-default p-0">
        <DialogHeader className="px-6 pt-5 pb-4 border-b border-border-default">
          <DialogTitle className="text-sm font-semibold text-text-primary tracking-wide">
            Add Widget
          </DialogTitle>
        </DialogHeader>

        {/* Widget grid grouped by category */}
        <div className="overflow-y-auto p-6 space-y-6">
          {categories.map((category) => {
            const widgets = widgetCatalog.filter(
              (w) => w.category === category
            );
            return (
              <div key={category}>
                <h3 className="text-xs font-medium text-text-muted uppercase tracking-widest mb-3">
                  {category}
                </h3>
                <div className="grid grid-cols-4 gap-2">
                  {widgets.map((widget) => {
                    const Icon: LucideIcon =
                      (LucideIcons as unknown as Record<string, LucideIcon>)[widget.icon] ||
                      LucideIcons.Box;
                    return (
                      <button
                        key={widget.id}
                        onClick={() => handleAddWidget(widget)}
                        className="flex flex-col items-center gap-2 p-3 rounded hover:bg-surface-hover transition-colors group"
                      >
                        <Icon
                          size={22}
                          className="text-text-secondary group-hover:text-text-primary transition-colors"
                        />
                        <span className="text-xs text-text-secondary group-hover:text-text-primary transition-colors text-center leading-tight">
                          {widget.name}
                        </span>
                      </button>
                    );
                  })}
                </div>
              </div>
            );
          })}
        </div>
      </DialogContent>
    </Dialog>
  );
}
