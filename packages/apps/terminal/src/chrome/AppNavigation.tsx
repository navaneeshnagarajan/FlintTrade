import { useCallback, useEffect, useRef, useState } from "react";
import { NavLink, Link, useLocation } from "react-router";
import { Activity, CandlestickChart, FlaskConical, GraduationCap, Landmark, NotebookPen, PieChart, Settings, Workflow } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { useSystemDiagnostics } from "@/hooks/useSystemDiagnostics";
import { APPS, type AppId } from "@/layout/appCatalog";
import { useAuthStore } from "@/stores/authStore";
import { useModeStore } from "@/stores/modeStore";
import { useDeveloperEnabled } from "./DeveloperPreference";
import { HelpFooterSlot } from "@/components/help/HelpFooter";
import { formatExchangeClock } from "./exchangeClock";

const APP_ICONS: Record<AppId, LucideIcon> = {
  terminal: CandlestickChart,
  testing: FlaskConical,
  portfolio: PieChart,
  automation: Workflow,
  reports: NotebookPen,
  learn: GraduationCap,
  brokers: Landmark,
  settings: Settings,
  system: Activity,
};

/** Which edges of the scrolling app bar still have apps beyond them. */
function overflowEdges(element: HTMLElement): { left: boolean; right: boolean } {
  return {
    left: element.scrollLeft > 1,
    right: element.scrollLeft + element.clientWidth < element.scrollWidth - 1,
  };
}

export function AppNavigation() {
  const developer = useDeveloperEnabled();
  const location = useLocation();
  const nav = useRef<HTMLElement>(null);
  const [edges, setEdges] = useState({ left: false, right: false });
  const measure = useCallback(() => {
    if (!nav.current) return;
    const next = overflowEdges(nav.current);
    setEdges(current => current.left === next.left && current.right === next.right ? current : next);
  }, []);
  // The bar scrolls sideways on a narrow window; keep the current app in view.
  useEffect(() => {
    nav.current?.querySelector<HTMLElement>("[aria-current='page']")?.scrollIntoView?.({ block: "nearest", inline: "nearest" });
    measure();
  }, [location.pathname, measure]);
  useEffect(() => {
    window.addEventListener("resize", measure);
    return () => window.removeEventListener("resize", measure);
  }, [measure]);
  // A faded edge is the cue that more apps are off-screen in that direction.
  const mask = edges.left || edges.right
    ? `linear-gradient(to right, ${edges.left ? "transparent, black 28px" : "black"}, ${edges.right ? "black calc(100% - 28px), transparent" : "black"})`
    : undefined;
  return <nav ref={nav} aria-label="Apps" onScroll={measure} style={mask ? { maskImage: mask, WebkitMaskImage: mask } : undefined} className="ft-scroll-quiet flex shrink-0 gap-1 overflow-x-auto border-b border-border-default bg-surface-base px-3 py-1">
    {developer && <span className="self-center px-2 text-xs text-warning">Developer</span>}
    {APPS.map(app => {
      const Icon = APP_ICONS[app.id];
      return <NavLink key={app.id} to={app.path} title={app.description} className={({ isActive }) => `flex shrink-0 items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent ${isActive ? "bg-accent/15 text-accent" : "text-text-secondary hover:bg-surface-hover hover:text-text-primary"}`}><Icon aria-hidden="true" className="size-3.5 shrink-0" />{app.name}</NavLink>;
    })}
  </nav>;
}
function percent(value: unknown, scope: unknown) {
  return scope === "host" && typeof value === "number" && Number.isFinite(value) ? `${value.toFixed(1)}%` : "Unavailable";
}
export function SystemStatusBar() {
  const authenticated = useAuthStore(s => s.status === "logged-in");
  const mode = useModeStore(s => s.mode);
  const health = useSystemDiagnostics();
  const data = authenticated && mode !== "explore" ? health.data?.resources : undefined;
  const metric = (value: unknown): Record<string, unknown> => value && typeof value === "object" ? value as Record<string, unknown> : {};
  // Host detail needs a wide bar. A phone keeps the link, the core state and Help on one line.
  const wide = "max-sm:hidden";
  return <footer className="flex min-h-8 shrink-0 flex-wrap items-center gap-x-4 gap-y-1 border-t border-border-default bg-surface-base px-3 py-0.5 text-xs text-text-secondary" data-testid="system-status-bar">
    <Link className="font-medium text-accent hover:underline" to="/system">System</Link>
    <span className="min-w-0 truncate">Core: {data ? health.isError ? "Last known · refresh failed" : String(data.status ?? "Unmeasured") : "Unavailable"}</span>
    <span className={wide}>Host CPU: {percent(metric(data?.cpu).used_pct, metric(data?.cpu).scope)}</span>
    <span className={wide}>RAM: {percent(metric(data?.memory).used_pct, metric(data?.memory).scope)}</span>
    <span className={wide}>GPU: {percent(metric(data?.gpu).used_pct, metric(data?.gpu).scope)}</span>
    <span className={wide} title="No measured browser-to-core timing source is connected to this bar">Browser RTT: Unmeasured</span>
    <span className={`ml-auto ${wide}`}>{data && health.dataUpdatedAt ? `Received ${formatExchangeClock(new Date(health.dataUpdatedAt))}` : "No host measurement"}</span>
    <span className="ml-auto sm:hidden" aria-hidden="true" />
    <HelpFooterSlot />
  </footer>;
}
