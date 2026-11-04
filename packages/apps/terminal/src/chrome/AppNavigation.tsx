import { useEffect, useId, useLayoutEffect, useRef, useState, type MouseEvent } from "react";
import { NavLink, Link, useLocation } from "react-router";
import { BookOpen, ChartNoAxesCombined, ChevronDown, FlaskConical, Landmark, ListChecks, PanelsTopLeft, Settings2, Workflow, Wrench } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import type { AppId } from "@/layout/appCatalog";
import { useSystemDiagnostics } from "@/hooks/useSystemDiagnostics";
import { APPS } from "@/layout/appCatalog";
import { useAuthStore } from "@/stores/authStore";
import { useModeStore } from "@/stores/modeStore";
import { useDeveloperEnabled } from "./DeveloperPreference";
import { HelpFooterSlot } from "@/components/help/HelpFooter";
import { Button } from "@/components/ui/button";

const GROUPS = ["Trading", "Studio", "Review"] as const;
type NavigationGroup = typeof GROUPS[number] | "Utilities";
// Presentation metadata only: paths, labels and capability ownership stay in APPS.
const PRESENTATION: Record<AppId, { group: NavigationGroup; icon: LucideIcon }> = {
  terminal: { group: "Trading", icon: PanelsTopLeft },
  portfolio: { group: "Trading", icon: ChartNoAxesCombined },
  brokers: { group: "Trading", icon: Landmark },
  testing: { group: "Studio", icon: FlaskConical },
  automation: { group: "Studio", icon: Workflow },
  learn: { group: "Studio", icon: BookOpen },
  reports: { group: "Review", icon: ListChecks },
  system: { group: "Review", icon: Wrench },
  settings: { group: "Utilities", icon: Settings2 },
};

function AppLinks({ group, onNavigate }: { group: NavigationGroup; onNavigate: (event: MouseEvent<HTMLAnchorElement>) => void }) {
  return <ul aria-label={group} className={group === "Utilities" ? "ft-app-nav-utilities" : undefined}>
    {APPS.filter(app => PRESENTATION[app.id].group === group).map(app => {
      const Icon = PRESENTATION[app.id].icon;
      return <li key={app.id}><NavLink to={app.path} onClick={onNavigate} className="ft-app-nav-link" title={app.description}>
        <Icon aria-hidden="true" /><span>{app.name}</span>
      </NavLink></li>;
    })}
  </ul>;
}

const COMPACT_NAV_QUERY = "(max-width: 767px)";

export function AppNavigation() {
  const developer = useDeveloperEnabled();
  const { pathname } = useLocation();
  const current = APPS.find(app => app.path === pathname);
  const [compact, setCompact] = useState(() => window.matchMedia(COMPACT_NAV_QUERY).matches);
  const [expanded, setExpanded] = useState(false);
  const navigation = useRef<HTMLElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const restoreFocus = useRef(false);
  const groupsId = useId();

  useEffect(() => {
    const media = window.matchMedia(COMPACT_NAV_QUERY);
    const update = () => {
      restoreFocus.current = navigation.current?.contains(document.activeElement) ?? false;
      setCompact(media.matches);
      setExpanded(false);
    };
    media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, []);
  useLayoutEffect(() => {
    if (!restoreFocus.current) return;
    restoreFocus.current = false;
    trigger.current?.focus({ preventScroll: true });
  }, [compact]);
  useEffect(() => { setExpanded(false); }, [pathname]);
  useEffect(() => {
    if (!expanded) return;
    const closeOutside = (event: PointerEvent) => {
      if (event.target instanceof Node && !navigation.current?.contains(event.target)) setExpanded(false);
    };
    document.addEventListener("pointerdown", closeOutside);
    return () => document.removeEventListener("pointerdown", closeOutside);
  }, [expanded]);

  function onNavigate(event: MouseEvent<HTMLAnchorElement>) {
    if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    setExpanded(false);
    // A same-route link does not run the shell's route-focus effect.
    if (event.currentTarget.pathname === pathname) trigger.current?.focus();
  }

  return <nav ref={navigation} aria-label="Apps" className="ft-app-nav" data-compact={compact} onBlur={event => {
    if (event.relatedTarget instanceof Node && !event.currentTarget.contains(event.relatedTarget)) setExpanded(false);
  }} onKeyDown={event => {
    if (event.key !== "Escape" || !expanded) return;
    event.preventDefault();
    event.stopPropagation();
    setExpanded(false);
    trigger.current?.focus();
  }}>
    <Button ref={trigger} type="button" variant="ghost" className="ft-app-nav-toggle justify-start" aria-label="Choose app" aria-expanded={expanded} aria-controls={groupsId} onClick={() => setExpanded(value => !value)}>
      <PanelsTopLeft aria-hidden="true" /><span>{current?.name ?? "Apps"}</span><ChevronDown aria-hidden="true" />
    </Button>
    <div id={groupsId} className="ft-app-nav-groups" hidden={!expanded}>
      {developer && <p className="px-2 text-xs text-warning">Developer</p>}
      {GROUPS.map(group => <div className="ft-app-nav-group" key={group}>
        <h2>{group}</h2><AppLinks group={group} onNavigate={onNavigate} />
      </div>)}
    </div>
    <AppLinks group="Utilities" onNavigate={onNavigate} />
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
  return <footer className="ft-system-status flex min-h-8 shrink-0 flex-wrap items-center gap-x-4 gap-y-1 border-t border-border-default bg-surface-base px-3 py-0.5 text-xs text-text-secondary" data-testid="system-status-bar">
    <Link className="font-medium text-accent" to="/system">System</Link>
    <span>Core: {data ? health.isError ? "Last known · refresh failed" : String(data.status ?? "Unmeasured") : "Unavailable"}</span>
    <span>Host CPU: {percent(metric(data?.cpu).used_pct, metric(data?.cpu).scope)}</span>
    <span>RAM: {percent(metric(data?.memory).used_pct, metric(data?.memory).scope)}</span>
    <span>GPU: {percent(metric(data?.gpu).used_pct, metric(data?.gpu).scope)}</span>
    <span title="No measured browser-to-core timing source is connected to this bar">Browser RTT: Unmeasured</span>
    <span className="ml-auto">{data && health.dataUpdatedAt ? `Received ${new Date(health.dataUpdatedAt).toLocaleTimeString()}` : "No host measurement"}</span>
    <HelpFooterSlot />
  </footer>;
}
