import { useRef, useEffect } from "react";
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
}

/**
 * ToolsDropdown — absolute-positioned dropdown.
 *
 * Route-aware behaviour:
 * - /trade   → shows all 4 trade tools; clicking any calls onSelectTool (canvas overlay)
 * - other    → shows Settings only; clicking navigates to /settings
 *
 * Closes when clicking outside (mousedown listener).
 * Positioned right-24 top-10 to sit beneath the TOOLS button in TopBar.
 */
export default function ToolsDropdown({
  isOpen,
  onClose,
  onSelectTool,
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

  return (
    <div
      ref={ref}
      className="absolute right-24 top-10 z-40 bg-surface-card border border-border-default rounded-lg shadow-xl py-1 w-52 animate-fade-in-scale"
    >
      {tools.map((tool) => {
        const Icon = tool.icon;
        return (
          <button
            key={tool.id}
            onClick={() => handleClick(tool)}
            className="w-full flex items-center gap-2.5 px-4 py-2 text-sm text-text-secondary hover:text-text-primary hover:bg-surface-hover transition-colors"
          >
            <Icon size={15} className="shrink-0" />
            <span>{tool.name}</span>
          </button>
        );
      })}
    </div>
  );
}
