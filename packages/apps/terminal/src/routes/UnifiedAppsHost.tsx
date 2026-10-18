import { lazy, Suspense, useEffect, useState } from "react";
import { useLocation } from "react-router";
import { APPS, appForPath, type AppId } from "@/layout/appCatalog";
import { RouteErrorBoundary } from "@/components/RouteErrorBoundary";
const UnifiedAppRoute = lazy(() => import("./UnifiedAppRoute"));

/** Retain docking owners above content Activities: FlexLayout needs attached
 * refs even during hidden background renders. UnifiedAppRoute suspends widget
 * effects, not docking refs. Lock/logout still unmount this entire owner. */
export function UnifiedAppsHost() {
  const location = useLocation();
  const current = appForPath(location.pathname);
  const [visited, setVisited] = useState<readonly AppId[]>([]);
  useEffect(() => { if (current) setVisited(previous => previous.includes(current) ? previous : [...previous, current]); }, [current]);
  const apps = current && !visited.includes(current) ? [...visited, current] : visited;
  return <div className="flex min-h-0 flex-1 flex-col">{apps.map(id => <div key={id} className={`${current === id ? "flex" : "hidden"} min-h-0 flex-1 flex-col`}>
    <RouteErrorBoundary routeName={APPS.find(app => app.id === id)!.name}><Suspense fallback={<p role="status">Loading app…</p>}><UnifiedAppRoute app={id} active={current === id} /></Suspense></RouteErrorBoundary>
  </div>)}</div>;
}
