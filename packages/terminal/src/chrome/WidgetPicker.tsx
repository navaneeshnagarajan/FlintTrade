import { useState, useRef, useEffect, useCallback } from "react";
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
  Search,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
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
  /**
   * Optional allowlist of widget IDs to show. When provided, only widgets
   * whose id is in this set are rendered. All others are omitted from the
   * picker entirely (not locked — they simply don't appear). This is used by
   * TerminalRoute to apply skill-level filtering via useSkillContent.
   */
  allowedIds?: ReadonlyArray<string>;
}

// ---------------------------------------------------------------------------
// Per-widget button — reads its own gate status (stable hook call count)
// ---------------------------------------------------------------------------

// ---------------------------------------------------------------------------
// Highlight matching text in widget names
// ---------------------------------------------------------------------------

function HighlightMatch({ text, query }: { text: string; query: string }) {
  if (!query) return <>{text}</>;
  const index = text.toLowerCase().indexOf(query.toLowerCase());
  if (index === -1) return <>{text}</>;
  return (
    <>
      {text.slice(0, index)}
      <mark className="bg-accent/25 text-accent rounded-sm px-0 not-italic">
        {text.slice(index, index + query.length)}
      </mark>
      {text.slice(index + query.length)}
    </>
  );
}

interface WidgetButtonProps {
  widget: WidgetMeta;
  onAdd: (widget: WidgetMeta) => void;
  onLocked: (widgetName: string) => void;
  searchQuery?: string;
}

function WidgetButton({ widget, onAdd, onLocked, searchQuery = "" }: WidgetButtonProps) {
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
        <HighlightMatch text={widget.name} query={searchQuery} />
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
 *
 * When `allowedIds` is provided (e.g. from useSkillContent), only widgets in
 * that set are shown. This keeps the picker uncluttered for lower skill levels
 * without touching the feature-gate system.
 */
export default function WidgetPicker({ isOpen, onClose, allowedIds }: WidgetPickerProps) {
  const dockviewApi = useLayoutStore((s) => s.dockviewApi);
  const [lockedNotice, setLockedNotice] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const searchInputRef = useRef<HTMLInputElement>(null);

  // Auto-focus search when dialog opens; clear query when it closes.
  useEffect(() => {
    if (isOpen) {
      // Let the dialog animation settle before focusing
      const timer = setTimeout(() => {
        searchInputRef.current?.focus();
      }, 50);
      return () => clearTimeout(timer);
    } else {
      setSearchQuery("");
    }
  }, [isOpen]);

  const handleAddWidget = useCallback((widget: WidgetMeta) => {
    if (!dockviewApi) return;
    const panelId = `${widget.id}-${Date.now()}`;
    dockviewApi.addPanel({
      id: panelId,
      component: widget.id,
      title: widget.name,
    });
    onClose();
  }, [dockviewApi, onClose]);

  const handleLocked = (widgetName: string) => {
    setLockedNotice(widgetName);
  };

  const handleClose = () => {
    setLockedNotice(null);
    setSearchQuery("");
    onClose();
  };

  // Apply skill-level allowlist when provided. Convert to a Set for O(1) lookup.
  const allowedSet = allowedIds ? new Set(allowedIds) : null;

  // Derive the catalog after applying the allowlist filter.
  const allowlistFiltered = allowedSet
    ? widgetCatalog.filter((w) => allowedSet.has(w.id))
    : widgetCatalog;

  // Apply search filter on top of the allowlist filter.
  const trimmedQuery = searchQuery.trim();
  const isSearching = trimmedQuery.length > 0;

  const searchFiltered = isSearching
    ? allowlistFiltered.filter((w) =>
        w.name.toLowerCase().includes(trimmedQuery.toLowerCase())
      )
    : allowlistFiltered;

  // Derive unique ordered category list for the grouped view.
  const categories: string[] = [];
  for (const w of allowlistFiltered) {
    if (!categories.includes(w.category)) categories.push(w.category);
  }

  // Handle Enter key on search — select the first matching result.
  function handleSearchKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Enter" && isSearching && searchFiltered.length > 0) {
      handleAddWidget(searchFiltered[0]);
    }
  }

  const matchCount = isSearching ? searchFiltered.length : allowlistFiltered.length;

  return (
    <Dialog open={isOpen} onOpenChange={(open) => { if (!open) handleClose(); }}>
      <DialogContent className="sm:max-w-130 max-h-[80vh] flex flex-col bg-surface-card border-border-default p-0 animate-fade-in-scale">
        <DialogHeader className="px-6 pt-5 pb-3 border-b border-border-default">
          <div className="flex items-center justify-between">
            <DialogTitle className="text-sm font-semibold text-text-primary tracking-wide">
              Add Widget
            </DialogTitle>
            <span className="text-xs text-text-muted tabular-nums" aria-live="polite">
              {isSearching ? `${matchCount} matching` : `${matchCount} widgets`}
            </span>
          </div>

          {/* Search input */}
          <div className="relative mt-3">
            <Search
              className="absolute left-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-text-muted pointer-events-none"
              aria-hidden="true"
            />
            <Input
              ref={searchInputRef}
              type="search"
              role="searchbox"
              aria-label="Search widgets"
              placeholder="Search widgets…"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              onKeyDown={handleSearchKeyDown}
              className="pl-8 h-8 text-sm bg-surface-base border-border-default placeholder:text-text-muted focus-visible:ring-accent/40"
            />
            {isSearching && (
              <button
                type="button"
                aria-label="Clear search"
                onClick={() => { setSearchQuery(""); searchInputRef.current?.focus(); }}
                className="absolute right-2.5 top-1/2 -translate-y-1/2 text-text-muted hover:text-text-primary transition-colors"
              >
                <X className="w-3.5 h-3.5" />
              </button>
            )}
          </div>
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

        {/* Widget grid — flat when searching, grouped by category otherwise */}
        <div className="overflow-y-auto p-6 flex-1 min-h-0">
          {isSearching ? (
            /* Flat search results */
            searchFiltered.length > 0 ? (
              <div className="grid grid-cols-4 gap-2">
                {searchFiltered.map((widget) => (
                  <WidgetButton
                    key={widget.id}
                    widget={widget}
                    onAdd={handleAddWidget}
                    onLocked={handleLocked}
                    searchQuery={trimmedQuery}
                  />
                ))}
              </div>
            ) : (
              <div className="flex flex-col items-center justify-center py-12 gap-2">
                <Search className="w-8 h-8 text-text-muted/40" aria-hidden="true" />
                <p className="text-sm text-text-muted">
                  No widgets match &ldquo;{trimmedQuery}&rdquo;
                </p>
              </div>
            )
          ) : (
            /* Grouped by category */
            <div className="space-y-6">
              {categories.map((category) => {
                const widgets = allowlistFiltered.filter((w) => w.category === category);
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
          )}
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
