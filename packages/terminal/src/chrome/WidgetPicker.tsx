import { useState } from "react";
import {
  LayoutDashboard,
  Zap,
  Table2,
  ClipboardList,
  Wallet,
  BookOpen,
  FileEdit,
  CandlestickChart,
  Grid3x3,
  BarChart3,
  Activity,
  Layers,
  Sigma,
  Star,
  Calculator,
  Newspaper,
  TrendingUp,
  Bot,
  Target,
  ShieldAlert,
  Map,
  Box,
  Lock,
  Eye,
  X,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { useLayoutStore } from "@/stores/layoutStore";
import { widgetCatalog } from "@/layout/widgetFactory";
import { useFeatureGate } from "@/hooks/useFeatureGate";
import type { GateStatus } from "@/hooks/useFeatureGate";
import type { WidgetMeta } from "@/types/widgets";
import { cn } from "@/lib/utils";

// Explicit icon registry — replaces `import * as LucideIcons` to allow tree-shaking.
// Only the icons actually used in widgetCatalog are imported here.
const ICON_MAP: Record<string, LucideIcon> = {
  LayoutDashboard,
  Zap,
  Table2,
  ClipboardList,
  Wallet,
  BookOpen,
  FileEdit,
  CandlestickChart,
  Grid3x3,
  BarChart3,
  Activity,
  Layers,
  Sigma,
  Star,
  Calculator,
  Newspaper,
  TrendingUp,
  Bot,
  Target,
  ShieldAlert,
  Map,
  Box,
};

interface WidgetPickerProps {
  isOpen: boolean;
  onClose: () => void;
}

// ---------------------------------------------------------------------------
// Per-widget button — reads its own gate status (stable hook call count)
// ---------------------------------------------------------------------------

interface WidgetButtonProps {
  widget: WidgetMeta;
  onAdd: (widget: WidgetMeta) => void;
  onLocked: (widgetName: string) => void;
}

function WidgetButton({ widget, onAdd, onLocked }: WidgetButtonProps) {
  const gateStatus: GateStatus = useFeatureGate(`widget:${widget.id}`, "trade");
  const Icon: LucideIcon = ICON_MAP[widget.icon] ?? Box;

  const isLocked = gateStatus === "locked";
  const isPreview = gateStatus === "preview";

  function handleClick() {
    if (isLocked) {
      onLocked(widget.name);
      return;
    }
    onAdd(widget);
  }

  return (
    <button
      onClick={handleClick}
      title={
        isLocked
          ? `${widget.name} — Unlock by reaching intermediate or advanced level`
          : isPreview
            ? `${widget.name} — Preview available`
            : widget.name
      }
      aria-label={
        isLocked
          ? `${widget.name} — locked`
          : isPreview
            ? `${widget.name} — preview`
            : `Add ${widget.name} widget`
      }
      className={cn(
        "relative flex flex-col items-center gap-2 p-3 rounded transition-colors group",
        isLocked
          ? "opacity-40 cursor-not-allowed hover:bg-surface-hover/40"
          : "hover:bg-surface-hover cursor-pointer",
      )}
    >
      {/* Preview badge */}
      {isPreview && (
        <span
          aria-hidden="true"
          className="absolute top-1.5 right-1.5 flex items-center gap-0.5 rounded px-1 py-0.5 bg-accent/15 border border-accent/30"
        >
          <Eye className="w-2.5 h-2.5 text-accent" />
          <span className="text-[9px] text-accent font-medium leading-none">Preview</span>
        </span>
      )}

      {/* Lock badge */}
      {isLocked && (
        <span
          aria-hidden="true"
          className="absolute top-1.5 right-1.5 flex items-center gap-0.5 rounded px-1 py-0.5 bg-surface-base border border-border-default"
        >
          <Lock className="w-2.5 h-2.5 text-text-muted" />
        </span>
      )}

      <Icon
        size={22}
        className={cn(
          "transition-colors",
          isLocked
            ? "text-text-muted"
            : "text-text-secondary group-hover:text-text-primary",
        )}
      />
      <span
        className={cn(
          "text-sm transition-colors text-center leading-tight",
          isLocked
            ? "text-text-muted"
            : "text-text-secondary group-hover:text-text-primary",
        )}
      >
        {widget.name}
      </span>
    </button>
  );
}

// ---------------------------------------------------------------------------
// Inline locked toast — shown at the bottom of the dialog
// ---------------------------------------------------------------------------

interface LockedNoticeProps {
  widgetName: string;
  onDismiss: () => void;
}

function LockedNotice({ widgetName, onDismiss }: LockedNoticeProps) {
  return (
    <div
      role="status"
      aria-live="polite"
      className="mx-6 mb-3 flex items-start gap-2.5 px-3 py-2.5 rounded-lg bg-surface-base border border-border-default text-xs text-text-secondary"
    >
      <Lock className="w-3.5 h-3.5 text-text-muted shrink-0 mt-0.5" />
      <span className="flex-1 leading-relaxed">
        <span className="font-medium text-text-primary">{widgetName}</span> is locked.
        Keep trading to reach intermediate level and unlock it.
      </span>
      <button
        type="button"
        onClick={onDismiss}
        aria-label="Dismiss"
        className="shrink-0 text-text-muted hover:text-text-primary transition-colors"
      >
        <X className="w-3.5 h-3.5" />
      </button>
    </div>
  );
}

/**
 * WidgetPicker -- shadcn Dialog for adding widgets to the Dockview canvas.
 * Uses dockviewApi from layoutStore to add panels directly.
 * Reads feature gate status per widget: locked widgets show a lock icon and
 * inform the user how to unlock; preview widgets show a subtle "Preview" badge.
 */
export default function WidgetPicker({ isOpen, onClose }: WidgetPickerProps) {
  const dockviewApi = useLayoutStore((s) => s.dockviewApi);
  const [lockedNotice, setLockedNotice] = useState<string | null>(null);

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

  const handleLocked = (widgetName: string) => {
    setLockedNotice(widgetName);
  };

  const handleClose = () => {
    setLockedNotice(null);
    onClose();
  };

  // Derive unique ordered category list from the catalog
  const categories: string[] = [];
  for (const w of widgetCatalog) {
    if (!categories.includes(w.category)) categories.push(w.category);
  }

  return (
    <Dialog open={isOpen} onOpenChange={(open) => { if (!open) handleClose(); }}>
      <DialogContent className="sm:max-w-130 max-h-[80vh] flex flex-col bg-surface-card border-border-default p-0 animate-fade-in-scale">
        <DialogHeader className="px-6 pt-5 pb-4 border-b border-border-default">
          <DialogTitle className="text-sm font-semibold text-text-primary tracking-wide">
            Add Widget
          </DialogTitle>
        </DialogHeader>

        {/* Legend */}
        <div className="px-6 py-2 border-b border-border-default flex items-center gap-4">
          <span className="flex items-center gap-1 text-xs text-text-muted">
            <Eye className="w-3 h-3 text-accent" />
            Preview
          </span>
          <span className="flex items-center gap-1 text-xs text-text-muted">
            <Lock className="w-3 h-3 text-text-muted" />
            Locked — unlock at intermediate/advanced level
          </span>
        </div>

        {/* Widget grid grouped by category */}
        <div className="overflow-y-auto p-6 space-y-6 flex-1 min-h-0">
          {categories.map((category) => {
            const widgets = widgetCatalog.filter(
              (w) => w.category === category
            );
            return (
              <div key={category}>
                <h3 className="text-xs font-heading font-medium text-text-muted uppercase tracking-widest mb-3">
                  {category}
                </h3>
                <div className="grid grid-cols-4 gap-2">
                  {widgets.map((widget) => (
                    <WidgetButton
                      key={widget.id}
                      widget={widget}
                      onAdd={handleAddWidget}
                      onLocked={handleLocked}
                    />
                  ))}
                </div>
              </div>
            );
          })}
        </div>

        {/* Locked notice — shown below the grid when a locked widget is clicked */}
        {lockedNotice && (
          <LockedNotice
            widgetName={lockedNotice}
            onDismiss={() => setLockedNotice(null)}
          />
        )}
      </DialogContent>
    </Dialog>
  );
}
