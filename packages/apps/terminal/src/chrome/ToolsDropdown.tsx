import { useRef, useEffect, useCallback } from "react";
import { createPortal } from "react-dom";
import { useLocation, useNavigate } from "react-router";
import {
  BookOpen,
  Settings,
  SlidersHorizontal,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import type { ToolId } from "@/types/widgets";

type ToolKind = "overlay" | "quick-settings" | "settings";

interface ToolEntry {
  id: string;
  name: string;
  icon: LucideIcon;
  kind: ToolKind;
}

/**
 * Tools available on the /trade route — these overlay the workspace canvas.
 *
 * "Market Intelligence" was removed here (ruling D4): every one of its tabs is
 * now served by a workspace widget — Market Overview (breadth, sectors, flows,
 * indices), OI Analytics (OI profile, signals, max pain), Dealer Gamma (GEX),
 * IV Smile & Skew, Correlation Matrix and Delivery Data.
 */
const TRADE_TOOLS: ToolEntry[] = [
  { id: "trade-journal", name: "Trade Review", icon: BookOpen, kind: "overlay" },
  { id: "quick-settings", name: "Quick Settings", icon: SlidersHorizontal, kind: "quick-settings" },
  { id: "settings", name: "Settings", icon: Settings, kind: "settings" },
];

/**
 * Off /trade there is no canvas overlay. Quick Settings still opens in place.
 * Settings navigates to the dedicated /settings route.
 */
const ROUTE_TOOLS: ToolEntry[] = [
  { id: "quick-settings", name: "Quick Settings", icon: SlidersHorizontal, kind: "quick-settings" },
  { id: "settings", name: "Settings", icon: Settings, kind: "settings" },
];

interface ToolsDropdownProps {
  isOpen: boolean;
  onClose: () => void;
  /** Called for canvas overlay tools, and for Settings on /trade. */
  onSelectTool: (toolId: ToolId) => void;
  /**
   * Opens the in-place density/theme panel. Must not navigate.
   * Always available — a skill allowlist cannot hide it.
   */
  onOpenQuickSettings: () => void;
  /**
   * Bounding rect of the TOOLS button — used for fixed portal positioning so
   * the dropdown escapes any parent overflow/stacking context (Issue #39).
   */
  anchorRect?: DOMRect;
  /**
   * Optional allowlist of overlay tool IDs on /trade. When provided, only
   * overlay tools whose id is in this set are rendered. Quick Settings and
   * Settings stay visible regardless. Supplied by TerminalRoute via
   * useSkillContent so beginners see fewer canvas tools.
   */
  allowedToolIds?: ReadonlyArray<string>;
}

/**
 * ToolsDropdown — portal-rendered dropdown anchored to the TOOLS button rect.
 *
 * Route-aware behaviour:
 * - /trade   → overlay tools call onSelectTool; Settings does too (the route
 *              navigates to /settings). Quick Settings opens the in-place panel.
 * - other    → Quick Settings opens in place; Settings navigates to /settings.
 *
 * Rendered via createPortal into document.body so it escapes any overflow or
 * stacking context in TopBar / AppLayout (Issue #39).
 * Closes when clicking outside (mousedown listener, Issue #75).
 */
export default function ToolsDropdown({
  isOpen,
  onClose,
  onSelectTool,
  onOpenQuickSettings,
  anchorRect,
  allowedToolIds,
}: ToolsDropdownProps) {
  const ref = useRef<HTMLDivElement>(null);
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;

  const location = useLocation();
  const navigate = useNavigate();

  const isTradeRoute = location.pathname === "/trade";

  // Skill allowlists filter overlay tools only. Quick Settings and Settings
  // stay visible on every route so desk controls are not skill-gated away.
  const tools: ToolEntry[] = (() => {
    const source = isTradeRoute ? TRADE_TOOLS : ROUTE_TOOLS;
    if (!allowedToolIds) return source;
    const allowed = new Set(allowedToolIds);
    return source.filter((tool) => tool.kind !== "overlay" || allowed.has(tool.id));
  })();

  useEffect(() => {
    if (!isOpen) return;
    const handleMouseDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        onCloseRef.current();
      }
    };
    document.addEventListener("mousedown", handleMouseDown);
    return () => document.removeEventListener("mousedown", handleMouseDown);
  }, [isOpen]);

  // Arrow key navigation between menu items
  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLDivElement>) => {
      if (e.key === "Escape") {
        onClose();
        return;
      }
      if (e.key === "ArrowDown" || e.key === "ArrowUp") {
        e.preventDefault();
        const items = ref.current?.querySelectorAll<HTMLButtonElement>("button[role='menuitem']");
        if (!items || items.length === 0) return;
        const idx = Array.from(items).indexOf(document.activeElement as HTMLButtonElement);
        const next =
          e.key === "ArrowDown"
            ? (idx + 1) % items.length
            : (idx - 1 + items.length) % items.length;
        items[next]?.focus();
      }
    },
    [onClose],
  );

  if (!isOpen) return null;

  function handleClick(tool: ToolEntry) {
    if (tool.kind === "quick-settings") {
      onOpenQuickSettings();
      onClose();
      return;
    }
    if (tool.kind === "settings") {
      if (isTradeRoute) {
        onSelectTool("settings");
      } else {
        navigate("/settings");
      }
      onClose();
      return;
    }
    onSelectTool(tool.id as ToolId);
    onClose();
  }

  // Fixed positioning anchored to the button's bounding rect (portal mode).
  // Falls back to a sensible default when no anchor rect is supplied.
  const positionStyle: React.CSSProperties = anchorRect
    ? {
        position: "fixed",
        top: anchorRect.bottom + 4,
        right: window.innerWidth - anchorRect.right,
      }
    : {
        position: "fixed",
        top: 44,
        right: 96,
      };

  return createPortal(
    <div
      ref={ref}
      role="menu"
      className="z-200 bg-surface-card border border-border-default rounded-lg shadow-xl py-1 w-52 animate-fade-in-scale"
      style={positionStyle}
      onKeyDown={handleKeyDown}
    >
      {tools.map((tool) => {
        const Icon = tool.icon;
        return (
          <button
            key={tool.id}
            type="button"
            role="menuitem"
            aria-haspopup={tool.kind === "quick-settings" ? "dialog" : undefined}
            onClick={() => handleClick(tool)}
            className="w-full flex items-center gap-2.5 px-4 py-2 text-sm text-text-secondary hover:text-text-primary hover:bg-surface-hover transition-colors"
          >
            <Icon size={15} className="shrink-0" aria-hidden="true" />
            <span>{tool.name}</span>
          </button>
        );
      })}
    </div>,
    document.body,
  );
}
