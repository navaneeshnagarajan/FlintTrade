import { NavLink, Link } from "react-router";
import { useSystemDiagnostics } from "@/hooks/useSystemDiagnostics";
import { APPS } from "@/layout/appCatalog";
import { useAuthStore } from "@/stores/authStore";
import { useModeStore } from "@/stores/modeStore";
import { useDeveloperEnabled } from "./DeveloperPreference";

export function AppNavigation() {
  const developer = useDeveloperEnabled();
  return <nav aria-label="Apps" className="flex shrink-0 gap-1 overflow-x-auto border-b border-border-default bg-surface-base px-3 py-1">
    {developer && <span className="self-center px-2 text-xs text-warning">Developer</span>}
    {APPS.map(app => <NavLink key={app.id} to={app.path} className={({ isActive }) => `shrink-0 rounded px-3 py-2 text-xs font-medium focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent ${isActive ? "bg-accent/15 text-accent" : "text-text-secondary hover:bg-surface-hover"}`}>{app.name}</NavLink>)}
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
  return <footer className="flex min-h-8 shrink-0 flex-wrap items-center gap-x-4 gap-y-1 border-t border-border-default bg-surface-base px-3 py-1 text-xs text-text-secondary" data-testid="system-status-bar">
    <Link className="font-medium text-accent" to="/system">System</Link>
    <span>Core: {data ? health.isError ? "Last known · refresh failed" : String(data.status ?? "Unmeasured") : "Unavailable"}</span>
    <span>Host CPU: {percent(metric(data?.cpu).used_pct, metric(data?.cpu).scope)}</span>
    <span>RAM: {percent(metric(data?.memory).used_pct, metric(data?.memory).scope)}</span>
    <span>GPU: {percent(metric(data?.gpu).used_pct, metric(data?.gpu).scope)}</span>
    <span title="No measured browser-to-core timing source is connected to this bar">Browser RTT: Unmeasured</span>
    <span className="ml-auto">{data && health.dataUpdatedAt ? `Received ${new Date(health.dataUpdatedAt).toLocaleTimeString()}` : "No host measurement"}</span>
  </footer>;
}
