// Vertical drawing toolbar — sits on the LEFT edge of the chart area.
// Each row shows the active tool for a group; a small chevron expands a popover
// with all tools in that group.  Favourites are pinned at the top.
// Group state and favourites persist in localStorage.

import { useState, useRef, useEffect, useCallback } from "react";
import {
  Crosshair,
  Eraser,
  TrendingUp,
  Minus,
  AlignJustify,
  ArrowRight,
  Infinity,
  LayoutGrid,
  Triangle,
  TrendingDown,
  Square,
  Circle,
  Pen,
  Type,
  MessageSquare,
  Tag,
  GitBranch,
  GitMerge,
  TrendingUp as LongIcon,
  TrendingDown as ShortIcon,
  Ruler,
  Lock,
  EyeOff,
  Trash2,
  ChevronRight,
  Star,
} from "lucide-react";
import type { DrawToolType } from "./types";

// ---------------------------------------------------------------------------
// Tool definitions
// ---------------------------------------------------------------------------

interface ToolDef {
  id: DrawToolType;
  label: string;
  icon: React.ReactNode;
  /** When true the tool has no backend implementation yet */
  comingSoon?: boolean;
}

interface ToolGroup {
  key: string;
  tools: ToolDef[];
}

const ICON_SIZE = 13;

const TOOL_GROUPS: ToolGroup[] = [
  {
    key: "cursor",
    tools: [
      { id: "cursor",  label: "Cursor",  icon: <Crosshair size={ICON_SIZE} /> },
      { id: "eraser",  label: "Eraser",  icon: <Eraser    size={ICON_SIZE} />, comingSoon: true },
    ],
  },
  {
    key: "lines",
    tools: [
      { id: "trendline",        label: "Trend Line",       icon: <TrendingUp    size={ICON_SIZE} /> },
      { id: "ray",              label: "Ray",               icon: <ArrowRight    size={ICON_SIZE} /> },
      { id: "extended_line",    label: "Extended Line",     icon: <Infinity      size={ICON_SIZE} />, comingSoon: true },
      { id: "hline",            label: "Horizontal Line",   icon: <Minus         size={ICON_SIZE} /> },
      { id: "vline",            label: "Vertical Line",     icon: <AlignJustify  size={ICON_SIZE} style={{ transform: "rotate(90deg)" }} /> },
      { id: "parallel_channel", label: "Parallel Channel",  icon: <LayoutGrid    size={ICON_SIZE} />, comingSoon: true },
    ],
  },
  {
    key: "fib",
    tools: [
      { id: "fib",           label: "Fib Retracement",  icon: <Triangle      size={ICON_SIZE} /> },
      { id: "fib_extension", label: "Fib Extension",    icon: <TrendingDown  size={ICON_SIZE} />, comingSoon: true },
    ],
  },
  {
    key: "shapes",
    tools: [
      { id: "rect",   label: "Rectangle",  icon: <Square  size={ICON_SIZE} /> },
      { id: "circle", label: "Circle",     icon: <Circle  size={ICON_SIZE} />, comingSoon: true },
      { id: "brush",  label: "Brush",      icon: <Pen     size={ICON_SIZE} />, comingSoon: true },
    ],
  },
  {
    key: "text",
    tools: [
      { id: "text",        label: "Text",         icon: <Type          size={ICON_SIZE} /> },
      { id: "callout",     label: "Callout",      icon: <MessageSquare size={ICON_SIZE} />, comingSoon: true },
      { id: "price_label", label: "Price Label",  icon: <Tag           size={ICON_SIZE} />, comingSoon: true },
    ],
  },
  {
    key: "patterns",
    tools: [
      { id: "elliott_impulse",    label: "Elliott Impulse",    icon: <GitBranch size={ICON_SIZE} />, comingSoon: true },
      { id: "elliott_correction", label: "Elliott Correction", icon: <GitMerge  size={ICON_SIZE} />, comingSoon: true },
    ],
  },
  {
    key: "prediction",
    tools: [
      { id: "long_position",  label: "Long Position",  icon: <LongIcon  size={ICON_SIZE} />, comingSoon: true },
      { id: "short_position", label: "Short Position", icon: <ShortIcon size={ICON_SIZE} />, comingSoon: true },
      { id: "measure",        label: "Measure",        icon: <Ruler     size={ICON_SIZE} />, comingSoon: true },
    ],
  },
];

// Action items — not DrawToolTypes, handled via callbacks
interface ActionItem {
  key: string;
  label: string;
  icon: React.ReactNode;
  onClick: () => void;
  destructive?: boolean;
}

// ---------------------------------------------------------------------------
// localStorage helpers
// ---------------------------------------------------------------------------

const LS_ACTIVE_KEY  = "flinttrade:drawtoolbar:active";
const LS_FAVS_KEY    = "flinttrade:drawtoolbar:favourites";

function loadActiveTools(): Record<string, DrawToolType> {
  try {
    const raw = localStorage.getItem(LS_ACTIVE_KEY);
    return raw ? (JSON.parse(raw) as Record<string, DrawToolType>) : {};
  } catch { return {}; }
}

function saveActiveTools(map: Record<string, DrawToolType>) {
  try { localStorage.setItem(LS_ACTIVE_KEY, JSON.stringify(map)); } catch { /* ignore */ }
}

function loadFavourites(): DrawToolType[] {
  try {
    const raw = localStorage.getItem(LS_FAVS_KEY);
    return raw ? (JSON.parse(raw) as DrawToolType[]) : [];
  } catch { return []; }
}

function saveFavourites(favs: DrawToolType[]) {
  try { localStorage.setItem(LS_FAVS_KEY, JSON.stringify(favs)); } catch { /* ignore */ }
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

interface TooltipProps {
  text: string;
  children: React.ReactNode;
}

function Tooltip({ text, children }: TooltipProps) {
  const [visible, setVisible] = useState(false);
  return (
    <div
      className="relative flex items-center justify-center"
      onMouseEnter={() => setVisible(true)}
      onMouseLeave={() => setVisible(false)}
    >
      {children}
      {visible && (
        <div className="pointer-events-none absolute left-full top-1/2 -translate-y-1/2 ml-2 z-200 whitespace-nowrap bg-surface-card border border-border-default text-text-primary text-xs rounded px-2 py-1 shadow-2xl">
          {text}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface DrawingToolbarProps {
  drawMode: DrawToolType | null;
  onToggle: (tool: DrawToolType) => void;
  onClearAll: () => void;
  onHideAll?: () => void;
  onLockAll?: () => void;
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export function DrawingToolbar({
  drawMode,
  onToggle,
  onClearAll,
  onHideAll,
  onLockAll,
}: DrawingToolbarProps) {
  // Per-group: which tool is the "active face" shown in the toolbar row
  const [activeTools, setActiveTools] = useState<Record<string, DrawToolType>>(loadActiveTools);

  // Set of pinned favourite tool ids
  const [favourites, setFavourites] = useState<DrawToolType[]>(loadFavourites);

  // Which group popover is currently open (key = group.key | "favourites" | null)
  const [openGroup, setOpenGroup] = useState<string | null>(null);

  // Tooltip for "coming soon" tools
  const [comingSoonTip, setComingSoonTip] = useState<string | null>(null);
  const comingSoonTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Close popover on outside click
  const toolbarRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    function handleOutside(e: MouseEvent) {
      if (toolbarRef.current && !toolbarRef.current.contains(e.target as Node)) {
        setOpenGroup(null);
      }
    }
    document.addEventListener("mousedown", handleOutside);
    return () => document.removeEventListener("mousedown", handleOutside);
  }, []);

  // Persist when either state changes
  useEffect(() => { saveActiveTools(activeTools); }, [activeTools]);
  useEffect(() => { saveFavourites(favourites);   }, [favourites]);

  const showComingSoon = useCallback((label: string) => {
    if (comingSoonTimer.current) clearTimeout(comingSoonTimer.current);
    setComingSoonTip(`${label} — coming soon`);
    comingSoonTimer.current = setTimeout(() => setComingSoonTip(null), 2000);
  }, []);

  // Handle tool button click (main icon or item in popover)
  const handleToolClick = useCallback((tool: ToolDef, groupKey: string) => {
    if (tool.comingSoon) {
      showComingSoon(tool.label);
      return;
    }
    // Update which tool is the face of this group
    setActiveTools((prev) => ({ ...prev, [groupKey]: tool.id }));
    setOpenGroup(null);
    onToggle(tool.id);
  }, [onToggle, showComingSoon]);

  const toggleFavourite = useCallback((id: DrawToolType) => {
    setFavourites((prev) =>
      prev.includes(id) ? prev.filter((f) => f !== id) : [...prev, id],
    );
  }, []);

  // Resolve a tool def by id (across all groups)
  function findToolDef(id: DrawToolType): ToolDef | undefined {
    for (const g of TOOL_GROUPS) {
      const found = g.tools.find((t) => t.id === id);
      if (found) return found;
    }
    return undefined;
  }

  // Action buttons (bottom section)
  const actions: ActionItem[] = [
    {
      key: "lock",
      label: "Lock drawings",
      icon: <Lock size={ICON_SIZE} />,
      onClick: () => { onLockAll?.(); setOpenGroup(null); },
    },
    {
      key: "hide",
      label: "Hide drawings",
      icon: <EyeOff size={ICON_SIZE} />,
      onClick: () => { onHideAll?.(); setOpenGroup(null); },
    },
    {
      key: "clear",
      label: "Clear all drawings",
      icon: <Trash2 size={ICON_SIZE} />,
      onClick: () => { onClearAll(); setOpenGroup(null); },
      destructive: true,
    },
  ];

  // ---------------------------------------------------------------------------
  // Render helpers
  // ---------------------------------------------------------------------------

  function renderToolRow(group: ToolGroup) {
    const faceId  = activeTools[group.key] ?? group.tools[0].id;
    const faceDef = group.tools.find((t) => t.id === faceId) ?? group.tools[0];
    const isOpen  = openGroup === group.key;
    const isActive = drawMode === faceDef.id;
    const hasArrow = group.tools.length > 1;

    return (
      <div key={group.key} className="relative flex items-center w-full">
        {/* Main icon button */}
        <Tooltip text={faceDef.label}>
          <button
            onClick={() => handleToolClick(faceDef, group.key)}
            className={[
              "flex items-center justify-center w-7 h-7 rounded transition-colors",
              isActive
                ? "bg-accent/15 text-accent"
                : "text-text-muted hover:text-text-primary hover:bg-surface-hover",
            ].join(" ")}
            aria-label={faceDef.label}
            aria-pressed={isActive}
          >
            {faceDef.icon}
          </button>
        </Tooltip>

        {/* Expand arrow */}
        {hasArrow && (
          <button
            onClick={(e) => {
              e.stopPropagation();
              setOpenGroup(isOpen ? null : group.key);
            }}
            className="flex items-center justify-center w-3 h-5 text-text-muted hover:text-text-primary transition-colors -ml-0.5"
            aria-label={`Expand ${group.key} tools`}
          >
            <ChevronRight size={8} />
          </button>
        )}

        {/* Group popover */}
        {isOpen && (
          <div className="absolute left-full top-0 ml-1 z-150 bg-surface-card border border-border-default rounded-lg shadow-2xl p-1 min-w-35">
            <div className="text-xxs text-text-muted uppercase tracking-wider px-2 py-0.5 mb-0.5 select-none">
              {group.key}
            </div>
            {group.tools.map((tool) => {
              const isFav = favourites.includes(tool.id);
              const isSelected = drawMode === tool.id;
              return (
                <div
                  key={tool.id}
                  className={[
                    "flex items-center gap-2 px-2 py-1 rounded cursor-pointer select-none transition-colors",
                    tool.comingSoon
                      ? "opacity-50 cursor-not-allowed"
                      : isSelected
                        ? "bg-accent/15 text-accent"
                        : "text-text-secondary hover:text-text-primary hover:bg-surface-hover",
                  ].join(" ")}
                  onClick={() => handleToolClick(tool, group.key)}
                >
                  <span className="shrink-0">{tool.icon}</span>
                  <span className="text-xs flex-1 whitespace-nowrap">{tool.label}</span>
                  {tool.comingSoon && (
                    <span className="text-xxs text-text-muted ml-auto">soon</span>
                  )}
                  {!tool.comingSoon && (
                    <button
                      onClick={(e) => { e.stopPropagation(); toggleFavourite(tool.id); }}
                      className={[
                        "ml-auto p-0.5 rounded transition-colors",
                        isFav ? "text-amber-400 hover:text-amber-300" : "text-text-muted hover:text-text-primary",
                      ].join(" ")}
                      title={isFav ? "Remove from favourites" : "Add to favourites"}
                      aria-label={isFav ? "Remove from favourites" : "Add to favourites"}
                    >
                      <Star size={9} fill={isFav ? "currentColor" : "none"} />
                    </button>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>
    );
  }

  function renderFavouritesRow() {
    if (favourites.length === 0) return null;
    const isOpen = openGroup === "favourites";
    return (
      <div className="relative flex items-center w-full">
        <Tooltip text="Favourites">
          <button
            onClick={() => setOpenGroup(isOpen ? null : "favourites")}
            className="flex items-center justify-center w-7 h-7 rounded text-amber-400 hover:bg-surface-hover transition-colors"
            aria-label="Favourites"
          >
            <Star size={ICON_SIZE} fill="currentColor" />
          </button>
        </Tooltip>
        {isOpen && (
          <div className="absolute left-full top-0 ml-1 z-150 bg-surface-card border border-border-default rounded-lg shadow-2xl p-1 min-w-35">
            <div className="text-xxs text-text-muted uppercase tracking-wider px-2 py-0.5 mb-0.5 select-none">
              Favourites
            </div>
            {favourites.map((id) => {
              const def = findToolDef(id);
              if (!def) return null;
              const groupKey = TOOL_GROUPS.find((g) => g.tools.some((t) => t.id === id))?.key ?? "";
              const isSelected = drawMode === id;
              return (
                <div
                  key={id}
                  className={[
                    "flex items-center gap-2 px-2 py-1 rounded cursor-pointer select-none transition-colors",
                    isSelected
                      ? "bg-accent/15 text-accent"
                      : "text-text-secondary hover:text-text-primary hover:bg-surface-hover",
                  ].join(" ")}
                  onClick={() => handleToolClick(def, groupKey)}
                >
                  <span className="shrink-0">{def.icon}</span>
                  <span className="text-xs flex-1 whitespace-nowrap">{def.label}</span>
                  <button
                    onClick={(e) => { e.stopPropagation(); toggleFavourite(id); }}
                    className="ml-auto p-0.5 rounded text-amber-400 hover:text-amber-300 transition-colors"
                    title="Remove from favourites"
                    aria-label="Remove from favourites"
                  >
                    <Star size={9} fill="currentColor" />
                  </button>
                </div>
              );
            })}
          </div>
        )}
      </div>
    );
  }

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  return (
    <div
      ref={toolbarRef}
      className="flex flex-col items-center gap-0.5 w-8 shrink-0 bg-surface-base border-r border-border-default py-1 select-none overflow-visible relative"
      aria-label="Drawing tools"
    >
      {/* Coming-soon flash */}
      {comingSoonTip && (
        <div className="pointer-events-none absolute left-full top-2 ml-2 z-200 whitespace-nowrap bg-surface-card border border-border-default text-text-muted text-xs rounded px-2 py-1 shadow-2xl">
          {comingSoonTip}
        </div>
      )}

      {/* Favourites row */}
      {renderFavouritesRow()}
      {favourites.length > 0 && <div className="h-px bg-border-default mx-1 w-full my-0.5" />}

      {/* Tool group rows */}
      {TOOL_GROUPS.map((group, i) => (
        <div key={group.key} className="flex flex-col items-center w-full">
          {renderToolRow(group)}
          {/* Separator between groups (not after last) */}
          {i < TOOL_GROUPS.length - 1 && (
            <div className="h-px bg-border-default mx-1 w-full my-0.5" />
          )}
        </div>
      ))}

      {/* Actions separator */}
      <div className="h-px bg-border-default mx-1 w-full my-0.5" />

      {/* Action buttons */}
      {actions.map((action) => (
        <Tooltip key={action.key} text={action.label}>
          <button
            onClick={action.onClick}
            className={[
              "flex items-center justify-center w-7 h-7 rounded transition-colors",
              action.destructive
                ? "text-text-muted hover:text-loss hover:bg-surface-hover"
                : "text-text-muted hover:text-text-primary hover:bg-surface-hover",
            ].join(" ")}
            aria-label={action.label}
          >
            {action.icon}
          </button>
        </Tooltip>
      ))}
    </div>
  );
}
