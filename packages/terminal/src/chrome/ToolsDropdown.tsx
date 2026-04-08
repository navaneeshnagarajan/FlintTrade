import { useRef, useEffect, useCallback } from "react";
import { createPortal } from "react-dom";
import { useLocation, useNavigate } from "react-router-dom";
import {
  PieChart,
  BarChart3,
  BookOpen,
  Settings,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import type { ToolId } from "@/types/widgets";

interface ToolEntry {
  id: ToolId;
  name: string;
  icon: LucideIcon;
}

/**
 * Tools available on the /trade route — these overlay the Dockview canvas.
 */
const TRADE_TOOLS: ToolEntry[] = [
  { id: "pnl-dashboard", name: "P&L Dashboard", icon: PieChart },
  { id: "market-intelligence", name: "Market Intelligence", icon: BarChart3 },
  { id: "trade-journal", name: "Trade Journal", icon: BookOpen },
  { id: "settings", name: "Settings", icon: Settings },
];

/**
 * On routes other than /trade, only Settings is available as an overlay-style
 * tool, and it navigates to the dedicated /settings route instead.
 */
const SETTINGS_ONLY: ToolEntry[] = [
  { id: "settings", name: "Settings", icon: Settings },
];

interface ToolsDropdownProps {
  isOpen: boolean;
  onClose: () => void;
  /** Called only when on /trade. On other routes, Settings navigates directly. */
  onSelectTool: (toolId: ToolId) => void;
  /**
   * Bounding rect of the TOOLS button — used for fixed portal positioning so
   * the dropdown escapes any parent overflow/stacking context (Issue #39).
   */
  anchorRect?: DOMRect;
}

/**
 * ToolsDropdown — portal-rendered dropdown anchored to the TOOLS button rect.
 *
 * Route-aware behaviour:
 * - /trade   → shows all 4 trade tools; clicking any calls onSelectTool (canvas overlay)
 * - other    → shows Settings only; clicking navigates to /settings
 *
 * Rendered via createPortal into document.body so it escapes any overflow or
 * stacking context in TopBar / AppLayout (Issue #39).
 * Closes when clicking outside (mousedown listener, Issue #75).
 */
export default function ToolsDropdown({
  isOpen,
  onClose,
  onSelectTool,
  anchorRect,
}: ToolsDropdownProps) {
  const ref = useRef<HTMLDivElement>(null);
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;

  const location = useLocation();
  const navigate = useNavigate();

  const isTradeRoute = location.pathname === "/trade";
  const tools = isTradeRoute ? TRADE_TOOLS : SETTINGS_ONLY;

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
    if (isTradeRoute) {
      onSelectTool(tool.id);
    } else {
      // On non-trade routes, Settings navigates to the dedicated route.
      navigate("/settings");
    }
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
      className="z-50 bg-surface-card border border-border-default rounded-lg shadow-xl py-1 w-52 animate-fade-in-scale"
      style={positionStyle}
      onKeyDown={handleKeyDown}
    >
      {tools.map((tool) => {
        const Icon = tool.icon;
        return (
          <button
            key={tool.id}
            role="menuitem"
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
