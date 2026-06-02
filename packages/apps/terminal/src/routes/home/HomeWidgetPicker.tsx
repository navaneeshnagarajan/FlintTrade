import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { HOME_WIDGET_CATALOG } from "@/routes/home/homeWidgetRegistry";

interface HomeWidgetPickerProps {
  isOpen: boolean;
  onClose: () => void;
  onAdd: (componentId: string) => void;
}

export function HomeWidgetPicker({ isOpen, onClose, onAdd }: HomeWidgetPickerProps) {
  return (
    <Dialog open={isOpen} onOpenChange={(open) => { if (!open) onClose(); }}>
      <DialogContent className="sm:max-w-2xl max-h-[85vh] flex flex-col bg-surface-card border-border-default p-0">
        <DialogHeader className="px-6 pt-5 pb-3 border-b border-border-default">
          <DialogTitle className="text-sm font-semibold text-text-primary tracking-wide">
            Add dashboard widget
          </DialogTitle>
          <DialogDescription className="text-xs text-text-muted">
            Choose a bento card to add to your home dashboard.
          </DialogDescription>
        </DialogHeader>

        <div className="overflow-y-auto p-6 flex-1 min-h-0">
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3">
            {HOME_WIDGET_CATALOG.map((widget) => {
              const Icon = widget.icon;
              return (
                <button
                  key={widget.componentId}
                  type="button"
                  onClick={() => onAdd(widget.componentId)}
                  aria-label={`Add ${widget.name} widget`}
                  className="group flex min-h-28 flex-col items-start gap-2 rounded border border-border-default bg-surface-base/70 p-3 text-left transition-colors hover:border-accent/50 hover:bg-surface-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/40"
                >
                  <Icon
                    size={18}
                    aria-hidden="true"
                    className="text-text-secondary transition-colors group-hover:text-accent"
                  />
                  <span className="text-sm font-medium leading-tight text-text-primary">
                    {widget.name}
                  </span>
                  <span className="text-[11px] leading-snug text-text-muted">
                    {widget.description}
                  </span>
                </button>
              );
            })}
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
