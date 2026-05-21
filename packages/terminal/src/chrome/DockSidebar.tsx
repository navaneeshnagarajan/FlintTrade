/**
 * DockSidebar.tsx
 *
 * macOS dock-style vertical sidebar for FlintTrade navigation.
 *
 * Modes:
 *   - icons (52px):      Icon-only, with tooltip on hover
 *   - expanded (160px):  Icon + label, always visible
 *   - auto-hide:         Collapses to 4px gradient strip, expands on mouse enter
 *   - hidden:            Zero width, effectively off
 *
 * Features:
 *   - Scale 1.12x + tooltip on hover (macOS magnification)
 *   - Active route: green left-edge indicator bar (3px × 16px)
 *   - Drag-and-drop reorder via framer-motion Reorder
 *   - Glass background (rgba(12,12,20,0.6) + blur 12px)
 *   - Separator items between groups
 */

import { useRef, useCallback, useEffect, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { motion, Reorder, useSpring, useTransform } from "framer-motion";
import {
  Home,
  TrendingUp,
  Wallet,
  BookOpen,
  FlaskConical,
  Zap,
  Bot,
  Copy,
  Shield,
  Settings,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { useSidebarStore } from "@/stores/sidebarStore";
import type { SidebarItem } from "@/stores/sidebarStore";

// ---------------------------------------------------------------------------
// Icon registry — explicit imports for tree-shaking
// ---------------------------------------------------------------------------

const ICON_MAP: Record<string, LucideIcon> = {
  Home,
  TrendingUp,
  Wallet,
  BookOpen,
  FlaskConical,
  Zap,
  Bot,
  Copy,
  Shield,
  Settings,
};

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const WIDTH_ICONS = 52;
const WIDTH_EXPANDED = 160;
const WIDTH_STRIP = 4;
const AUTO_HIDE_COLLAPSE_DELAY = 300;

// ---------------------------------------------------------------------------
// DockItemTooltip
// ---------------------------------------------------------------------------

interface TooltipProps {
  label: string;
  visible: boolean;
}

function DockItemTooltip({ label, visible }: TooltipProps) {
  return (
    <motion.div
      role="tooltip"
      initial={{ opacity: 0, x: -6 }}
      animate={{ opacity: visible ? 1 : 0, x: visible ? 0 : -6 }}
      transition={{ duration: 0.15, ease: "easeOut" }}
      style={{ pointerEvents: "none" }}
      className="absolute left-[52px] top-1/2 -translate-y-1/2 z-50 ml-2
                 px-2.5 py-1 rounded-md text-xs font-medium whitespace-nowrap
                 text-[var(--color-text)] select-none"
      aria-hidden={!visible}
    >
      {/* Glass background */}
      <span
        className="absolute inset-0 rounded-md border border-white/[0.08]"
        style={{
          background: "rgba(20,20,32,0.88)",
          backdropFilter: "blur(8px)",
        }}
        aria-hidden="true"
      />
      <span className="relative z-10">{label}</span>
    </motion.div>
  );
}

// ---------------------------------------------------------------------------
// ActiveIndicator
// ---------------------------------------------------------------------------

function ActiveIndicator() {
  return (
    <motion.span
      data-testid="active-indicator"
      layoutId="sidebar-active-indicator"
      className="absolute left-0 top-1/2 -translate-y-1/2 w-[3px] h-4 rounded-r-full bg-[var(--color-profit,#22c55e)]"
      transition={{ type: "spring", stiffness: 400, damping: 30 }}
      aria-hidden="true"
    />
  );
}

// ---------------------------------------------------------------------------
// DockRouteItem
// ---------------------------------------------------------------------------

interface DockRouteItemProps {
  item: SidebarItem;
  isActive: boolean;
  showLabel: boolean;
  onNavigate: (route: string) => void;
}

function DockRouteItem({ item, isActive, showLabel, onNavigate }: DockRouteItemProps) {
  const [hovered, setHovered] = useState(false);
  const Icon = ICON_MAP[item.icon] ?? Home;

  const handleClick = useCallback(() => {
    onNavigate(item.route);
  }, [item.route, onNavigate]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        onNavigate(item.route);
      }
    },
    [item.route, onNavigate],
  );

  return (
    <div className="relative flex items-center" data-testid={`sidebar-item-${item.id}`}>
      {isActive && <ActiveIndicator />}

      {/* Show tooltip only in icons mode (no label shown) */}
      {!showLabel && (
        <DockItemTooltip label={item.label} visible={hovered} />
      )}

      <motion.button
        type="button"
        aria-label={item.label}
        aria-current={isActive ? "page" : undefined}
        data-testid={`sidebar-item-${item.id}-button`}
        onClick={handleClick}
        onKeyDown={handleKeyDown}
        onHoverStart={() => setHovered(true)}
        onHoverEnd={() => setHovered(false)}
        whileHover={{ scale: 1.12 }}
        whileTap={{ scale: 0.96 }}
        transition={{ type: "spring", stiffness: 400, damping: 20 }}
        className={[
          "relative flex items-center gap-2.5 rounded-[10px] transition-colors duration-150 outline-none",
          "focus-visible:ring-2 focus-visible:ring-[var(--color-accent)]/60",
          showLabel
            ? "w-full px-3 py-2 justify-start"
            : "w-9 h-9 justify-center",
          isActive
            ? "bg-white/[0.08] text-[var(--color-text)]"
            : "text-[var(--color-text-muted)] hover:text-[var(--color-text)] hover:bg-white/[0.05]",
        ].join(" ")}
      >
        <Icon
          size={16}
          strokeWidth={isActive ? 2 : 1.75}
          aria-hidden="true"
          className="shrink-0"
        />
        {showLabel && (
          <motion.span
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            className="text-xs font-medium truncate"
          >
            {item.label}
          </motion.span>
        )}
      </motion.button>
    </div>
  );
}

// ---------------------------------------------------------------------------
// DockSeparator
// ---------------------------------------------------------------------------

function DockSeparator({ id }: { id: string }) {
  return (
    <div
      data-testid={`sidebar-separator-${id}`}
      aria-hidden="true"
      className="w-6 h-px mx-auto my-0.5 bg-white/[0.08]"
    />
  );
}

// ---------------------------------------------------------------------------
// AutoHideStrip — 4px gradient strip shown when sidebar is collapsed
// ---------------------------------------------------------------------------

interface AutoHideStripProps {
  onEnter: () => void;
  onLeave: () => void;
}

function AutoHideStrip({ onEnter, onLeave }: AutoHideStripProps) {
  return (
    <motion.div
      data-testid="auto-hide-strip"
      className="h-full cursor-pointer"
      style={{ width: WIDTH_STRIP }}
      tabIndex={0}
      role="button"
      aria-label="Expand navigation sidebar"
      onFocus={onEnter}
      onBlur={onLeave}
      onKeyDown={(e: React.KeyboardEvent) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onEnter();
        }
      }}
      onHoverStart={onEnter}
      initial={{ opacity: 0.6 }}
      whileHover={{ opacity: 1 }}
      whileFocus={{ opacity: 1 }}
      transition={{ duration: 0.2 }}
    >
      <div
        className="h-full w-full rounded-r-full"
        style={{
          background: "linear-gradient(180deg, var(--color-profit,#22c55e) 0%, #a855f7 60%, transparent 100%)",
          opacity: 0.7,
        }}
        aria-hidden="true"
      />
    </motion.div>
  );
}

// ---------------------------------------------------------------------------
// DockSidebar
// ---------------------------------------------------------------------------

/**
 * DockSidebar — macOS dock-style vertical navigation sidebar.
 *
 * Wire into AppLayout by replacing the current navigation with this component.
 */
export default function DockSidebar() {
  const location = useLocation();
  const navigate = useNavigate();
  const { mode, items, isHovered, setHovered } = useSidebarStore();

  // Auto-hide collapse timer ref
  const collapseTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const handleNavigate = useCallback(
    (route: string) => {
      if (route) navigate(route);
    },
    [navigate],
  );

  // Determine if the sidebar is currently showing content
  // (expanded strip in auto-hide while hovered)
  const isAutoHideExpanded = mode === "auto-hide" && isHovered;
  const showLabel = mode === "expanded" || isAutoHideExpanded;

  const targetWidth =
    mode === "hidden"
      ? 0
      : mode === "auto-hide" && !isHovered
        ? WIDTH_STRIP
        : mode === "expanded" || isAutoHideExpanded
          ? WIDTH_EXPANDED
          : WIDTH_ICONS;

  const springWidth = useSpring(targetWidth, { stiffness: 320, damping: 28 });
  // Keep spring in sync with targetWidth changes
  useEffect(() => {
    springWidth.set(targetWidth);
  }, [targetWidth, springWidth]);

  // Opacity: hidden mode → 0
  const opacity = useTransform(springWidth, [0, 4, WIDTH_ICONS], [0, 1, 1]);

  const handleMouseEnter = useCallback(() => {
    if (collapseTimer.current) clearTimeout(collapseTimer.current);
    setHovered(true);
  }, [setHovered]);

  const handleMouseLeave = useCallback(() => {
    collapseTimer.current = setTimeout(() => {
      setHovered(false);
    }, AUTO_HIDE_COLLAPSE_DELAY);
  }, [setHovered]);

  useEffect(() => {
    return () => {
      if (collapseTimer.current) clearTimeout(collapseTimer.current);
    };
  }, []);

  // -------------------------------------------------------------------------
  // Render: hidden
  // -------------------------------------------------------------------------

  if (mode === "hidden") return null;

  // -------------------------------------------------------------------------
  // Render: auto-hide strip (collapsed)
  // -------------------------------------------------------------------------

  if (mode === "auto-hide" && !isHovered) {
    return (
      <aside
        aria-label="Navigation sidebar (collapsed)"
        className="relative h-full shrink-0 flex items-center"
        style={{ width: WIDTH_STRIP }}
        onMouseEnter={handleMouseEnter}
      >
        <AutoHideStrip onEnter={handleMouseEnter} onLeave={handleMouseLeave} />
      </aside>
    );
  }

  // -------------------------------------------------------------------------
  // Render: expanded sidebar (icons / expanded / auto-hide expanded)
  // -------------------------------------------------------------------------

  // Separate settings from main items for fixed-bottom positioning
  const settingsItem = items.find((i) => i.id === "settings");
  const mainItems = items.filter((i) => i.id !== "settings");

  return (
    <motion.aside
      aria-label="Navigation sidebar"
      className="relative h-full flex flex-col py-3 shrink-0 overflow-visible"
      style={{
        width: springWidth,
        opacity,
        background: "rgba(12,12,20,0.6)",
        backdropFilter: "blur(12px)",
        WebkitBackdropFilter: "blur(12px)",
        borderRight: "1px solid rgba(255,255,255,0.04)",
      }}
      onMouseEnter={handleMouseEnter}
      onMouseLeave={handleMouseLeave}
    >
      {/* Main nav items — reorderable */}
      <nav aria-label="Main navigation" className="flex-1 flex flex-col gap-0.5 px-2 overflow-visible">
        <Reorder.Group
          axis="y"
          values={mainItems}
          onReorder={(newOrder) => {
            // Find new indices relative to the full items list
            // and reorder by rebuilding the list
            useSidebarStore.setState((state) => {
              const settingsIdx = state.items.findIndex((i) => i.id === "settings");
              const settingsEntry = settingsIdx >= 0 ? [state.items[settingsIdx]] : [];
              return { items: [...newOrder, ...settingsEntry] };
            });
          }}
          className="flex flex-col gap-0.5"
          style={{ listStyle: "none", padding: 0, margin: 0 }}
        >
          {mainItems.map((item, index) =>
            item.type === "separator" ? (
              <Reorder.Item
                key={item.id}
                value={item}
                drag={false}
                style={{ listStyle: "none" }}
              >
                <DockSeparator id={item.id} />
              </Reorder.Item>
            ) : (
              <Reorder.Item
                key={item.id}
                value={item}
                style={{ listStyle: "none", position: "relative" }}
                whileDrag={{ scale: 1.05, zIndex: 50, cursor: "grabbing" }}
                dragTransition={{ bounceStiffness: 600, bounceDamping: 20 }}
                data-index={index}
              >
                <DockRouteItem
                  item={item}
                  isActive={
                    item.route === "/"
                      ? location.pathname === "/"
                      : location.pathname.startsWith(item.route)
                  }
                  showLabel={showLabel}
                  onNavigate={handleNavigate}
                />
              </Reorder.Item>
            ),
          )}
        </Reorder.Group>
      </nav>

      {/* Settings — always pinned at bottom, not reorderable */}
      {settingsItem && (
        <div
          className="px-2 pt-1 mt-auto"
          data-testid="sidebar-settings-section"
        >
          <DockSeparator id="sep-bottom" />
          <div className="mt-0.5">
            <DockRouteItem
              item={settingsItem}
              isActive={location.pathname.startsWith("/settings")}
              showLabel={showLabel}
              onNavigate={handleNavigate}
            />
          </div>
        </div>
      )}
    </motion.aside>
  );
}
