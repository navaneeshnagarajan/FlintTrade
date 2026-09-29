/**
 * DockSidebar.tsx
 *
 * App navigation sidebar.
 *
 * Modes:
 *   - expanded (224px):  icon + label, grouped under headings (default on desk)
 *   - icons (56px):      icon rail with tooltips (Compact Trade, narrow windows)
 *   - auto-hide:         collapses to a 4px strip, expands on hover or focus
 *   - hidden:            off
 * Under 768px the sidebar becomes an off-canvas drawer opened from the
 * TopBar menu button.
 *
 * Features:
 *   - Active route: accent edge bar, filled row, aria-current="page"
 *   - Labelled groups (separators carry the group heading)
 *   - Drag-and-drop reorder via framer-motion Reorder
 *   - Settings pinned to the bottom
 */

import { useRef, useCallback, useEffect, useState } from "react";
import { useLocation, useNavigate } from "react-router";
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
  Users,
  Shield,
  Settings,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { LogoIcon } from "@/components/brand/Logo";
import { useDeskDensityChrome } from "@/hooks/useDeskDensityChrome";
import { cn } from "@/lib/utils";
import { useSidebarStore } from "@/stores/sidebarStore";
import type { SidebarItem } from "@/stores/sidebarStore";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetTitle,
} from "@/components/ui/sheet";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";

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
  Users,
  Shield,
  Settings,
};

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const WIDTH_ICONS = 56;
const WIDTH_EXPANDED = 224;
const WIDTH_STRIP = 4;
const AUTO_HIDE_COLLAPSE_DELAY = 300;
const DRAWER_QUERY = "(max-width: 767px)";

function isRouteActive(route: string, pathname: string): boolean {
  if (route === "/") return pathname === "/";
  return pathname === route || pathname.startsWith(`${route}/`);
}

function useDrawerViewport(): boolean {
  const [matches, setMatches] = useState(() =>
    typeof window !== "undefined" && typeof window.matchMedia === "function"
      ? window.matchMedia(DRAWER_QUERY).matches
      : false,
  );
  useEffect(() => {
    if (typeof window.matchMedia !== "function") return;
    const media = window.matchMedia(DRAWER_QUERY);
    const onChange = (event: MediaQueryListEvent) => setMatches(event.matches);
    setMatches(media.matches);
    media.addEventListener("change", onChange);
    return () => media.removeEventListener("change", onChange);
  }, []);
  return matches;
}

// ---------------------------------------------------------------------------
// ActiveIndicator
// ---------------------------------------------------------------------------

function ActiveIndicator() {
  return (
    <span
      data-testid="active-indicator"
      className="absolute left-0 top-1/2 h-5 w-[3px] -translate-y-1/2 rounded-r-full bg-accent"
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
  const Icon = ICON_MAP[item.icon] ?? Home;

  const button = (
    <button
      type="button"
      aria-label={item.label}
      aria-current={isActive ? "page" : undefined}
      data-testid={`sidebar-item-${item.id}-button`}
      onClick={() => onNavigate(item.route)}
      className={cn(
        "relative flex items-center rounded-md transition-colors duration-150 outline-none",
        "focus-visible:ring-2 focus-visible:ring-accent/60",
        showLabel ? "h-9 w-full gap-3 px-2.5 text-sm" : "mx-auto size-10 justify-center",
        isActive
          ? "bg-surface-hover font-medium text-text-primary"
          : "text-text-secondary hover:bg-surface-hover/60 hover:text-text-primary",
      )}
    >
      <Icon
        size={18}
        strokeWidth={isActive ? 2 : 1.75}
        aria-hidden="true"
        className={cn("shrink-0", isActive ? "text-accent" : undefined)}
      />
      {showLabel && <span className="truncate">{item.label}</span>}
    </button>
  );

  return (
    <div className="relative flex items-center" data-testid={`sidebar-item-${item.id}`}>
      {isActive && <ActiveIndicator />}

      {showLabel ? (
        button
      ) : (
        <Tooltip>
          <TooltipTrigger asChild>{button}</TooltipTrigger>
          <TooltipContent
            side="right"
            sideOffset={8}
            collisionPadding={8}
            className="max-w-48 whitespace-normal border border-border-default bg-surface-card text-text-primary shadow-floating"
          >
            {item.label}
          </TooltipContent>
        </Tooltip>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// DockSeparator — a group heading when labelled and expanded, else a rule
// ---------------------------------------------------------------------------

function DockSeparator({ id, label, showLabel }: { id: string; label?: string; showLabel: boolean }) {
  if (label && showLabel) {
    return (
      <div
        data-testid={`sidebar-separator-${id}`}
        role="presentation"
        className="ft-text-overline select-none px-2.5 pb-1 pt-4 text-text-muted"
      >
        {label}
      </div>
    );
  }
  return (
    <div
      data-testid={`sidebar-separator-${id}`}
      aria-hidden="true"
      className="mx-auto my-2 h-px w-6 bg-border-default"
    />
  );
}

// ---------------------------------------------------------------------------
// AutoHideStrip — 4px strip shown when the sidebar is collapsed
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
      <div className="h-full w-full rounded-r-full bg-accent/60" aria-hidden="true" />
    </motion.div>
  );
}

// ---------------------------------------------------------------------------
// MobileNavDrawer — the whole navigation in an off-canvas sheet
// ---------------------------------------------------------------------------

function MobileNavDrawer({
  items,
  pathname,
  open,
  onOpenChange,
  onNavigate,
}: {
  items: SidebarItem[];
  pathname: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onNavigate: (route: string) => void;
}) {
  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="left" className="w-72 gap-0 border-border-default bg-surface-base p-0">
        <div className="flex h-12 items-center gap-2 border-b border-border-default px-4">
          <LogoIcon size={20} aria-hidden />
          <SheetTitle className="font-heading text-sm font-bold text-text-primary">FlintTrade</SheetTitle>
          <SheetDescription className="sr-only">Go to any part of FlintTrade.</SheetDescription>
        </div>
        <nav aria-label="Main navigation" className="flex-1 overflow-y-auto px-2 py-2">
          {items.map((item) =>
            item.type === "separator" ? (
              <DockSeparator key={item.id} id={item.id} label={item.label} showLabel />
            ) : (
              <DockRouteItem
                key={item.id}
                item={item}
                isActive={isRouteActive(item.route, pathname)}
                showLabel
                onNavigate={onNavigate}
              />
            ),
          )}
        </nav>
      </SheetContent>
    </Sheet>
  );
}

// ---------------------------------------------------------------------------
// DockSidebar
// ---------------------------------------------------------------------------

export default function DockSidebar() {
  const location = useLocation();
  const navigate = useNavigate();
  const { mode: storedMode, items, isHovered, setHovered, mobileOpen, setMobileOpen } = useSidebarStore();
  const { dockModeFor } = useDeskDensityChrome();
  const mode = dockModeFor(storedMode);
  const drawer = useDrawerViewport();

  const collapseTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const handleNavigate = useCallback(
    (route: string) => {
      if (route) navigate(route);
      if (drawer) setMobileOpen(false);
    },
    [drawer, navigate, setMobileOpen],
  );

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

  const springWidth = useSpring(targetWidth, { stiffness: 380, damping: 36 });
  useEffect(() => {
    springWidth.set(targetWidth);
  }, [targetWidth, springWidth]);

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

  if (drawer) {
    return (
      <MobileNavDrawer
        items={items}
        pathname={location.pathname}
        open={Boolean(mobileOpen)}
        onOpenChange={setMobileOpen}
        onNavigate={handleNavigate}
      />
    );
  }

  if (mode === "hidden") return null;

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

  // Settings is pinned to the bottom and is not reorderable.
  const settingsItem = items.find((i) => i.id === "settings");
  const mainItems = items.filter((i) => i.id !== "settings");

  return (
    <motion.aside
      aria-label="Navigation sidebar"
      className="relative flex h-full shrink-0 flex-col overflow-hidden"
      style={{
        width: springWidth,
        opacity,
        background: "var(--glass-chrome-bg, rgba(12,12,20,0.6))",
        borderRight: "1px solid var(--glass-chrome-border, rgba(255,255,255,0.04))",
      }}
      onMouseEnter={handleMouseEnter}
      onMouseLeave={handleMouseLeave}
    >
      <TooltipProvider delayDuration={200}>
        <nav aria-label="Main navigation" className="flex min-h-0 flex-1 flex-col">
          <div className="flex min-h-0 flex-1 flex-col overflow-y-auto overflow-x-hidden px-2 py-3 [scrollbar-width:none]">
            <Reorder.Group
              axis="y"
              values={mainItems}
              onReorder={(newOrder) => {
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
                    <DockSeparator id={item.id} label={item.label} showLabel={showLabel} />
                  </Reorder.Item>
                ) : (
                  <Reorder.Item
                    key={item.id}
                    value={item}
                    style={{ listStyle: "none", position: "relative" }}
                    whileDrag={{ scale: 1.02, zIndex: 50, cursor: "grabbing" }}
                    dragTransition={{ bounceStiffness: 600, bounceDamping: 20 }}
                    data-index={index}
                  >
                    <DockRouteItem
                      item={item}
                      isActive={isRouteActive(item.route, location.pathname)}
                      showLabel={showLabel}
                      onNavigate={handleNavigate}
                    />
                  </Reorder.Item>
                ),
              )}
            </Reorder.Group>
          </div>

          {settingsItem && (
            <div
              className="shrink-0 border-t border-border-subtle px-2 py-2"
              data-testid="sidebar-settings-section"
            >
              <DockRouteItem
                item={settingsItem}
                isActive={isRouteActive(settingsItem.route, location.pathname)}
                showLabel={showLabel}
                onNavigate={handleNavigate}
              />
            </div>
          )}
        </nav>
      </TooltipProvider>
    </motion.aside>
  );
}
