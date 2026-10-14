import React, { lazy, Suspense, type ComponentType, type PropsWithChildren } from "react";
import { initialiseGlitchtip } from "./lib/glitchtip";
import { createBrowserRouter, Navigate, useLocation } from "react-router";
import { APPS, appForPath, appPath } from "./layout/appCatalog";
import { DESK_ROUTE_ALIASES, PUBLIC_ENTRY_REDIRECTS } from "./routes/deskAliases";
// RouterProvider must come from react-router/dom: the root export is the
// non-DOM variant without ReactDOM.flushSync wiring, so navigate/submit
// flushSync opt-ins would silently degrade to transitions.
import { RouterProvider } from "react-router/dom";
import { Provider as JotaiProvider } from "jotai";
import { QueryProvider } from "./providers/QueryProvider";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { RouteErrorBoundary } from "./components/RouteErrorBoundary";
import { renderReactRoot } from "./lib/reactRoot";
import { exploreRoutePolicy, isPublicDemoBuild } from "./lib/demoSession";
import {
  CANONICAL_SETUP_PATH,
  LEGACY_SETUP_ACCOUNT_PATH,
  SetupAccountAlias,
} from "./routes/setupRouting";
import RootLayout from "./routes/RootLayout";
import AppLayout from "./routes/AppLayout";
import ProtectedRoute from "./routes/ProtectedRoute";
import "./index.css";

/**
 * Build-aware `/explore` route contract (see `exploreRoutePolicy` in demoSession):
 * - Public demo build: render ExploreRoute for marketing/demo URL compatibility.
 * - Installed build: redirect bare `/explore` to welcome/onboarding. Sample-data
 *   entry is Welcome "Try with sample data" → Home in Explore mode, not ExploreRoute.
 */
function ExplorePathElement() {
  const policy = exploreRoutePolicy();
  if (policy.kind === "redirect") {
    return <Navigate to={policy.to} replace />;
  }
  return (
    <RouteErrorBoundary routeName="Demo (example data)">
      <Suspense fallback={<Loading />}>
        <ExploreRoute />
      </Suspense>
    </RouteErrorBoundary>
  );
}

// ---------------------------------------------------------------------------
// Glitchtip error tracking — Sentry SDK compatible (MIT).
// DSN is empty in dev (no error reporting). Set VITE_GLITCHTIP_DSN in production.
// ---------------------------------------------------------------------------
const glitchtipDsn = import.meta.env.VITE_GLITCHTIP_DSN as string | undefined;
if (glitchtipDsn && !isPublicDemoBuild()) {
  // Keep the build-time guard so an unconfigured build can omit the SDK.
  void initialiseGlitchtip(glitchtipDsn, import.meta.env.DEV ? "development" : "production");
}

const CanonicalSetupRoute = lazy(() => import("./routes/CanonicalSetupRoute"));
const WelcomeRoute = lazy(() => import("./routes/WelcomeRoute"));
const ExploreRoute = lazy(() => import("./routes/ExploreRoute"));
const NotFoundRoute = lazy(() => import("./routes/NotFoundRoute"));

function Loading() {
  return (
    <div className="flex items-center justify-center h-screen bg-surface-base" role="status">
      <div className="flex flex-col items-center gap-3">
        <div className="w-8 h-8 border-2 border-accent/30 border-t-accent rounded-full animate-spin" />
        <p className="text-sm text-text-muted animate-pulse">Loading FlintTrade...</p>
      </div>
    </div>
  );
}

/**
 * Determine the initial route based on persisted settings.
 * First-time users (no settings) go to /welcome.
 * Returning users enter the shared Terminal; preferences confer no authority.
 */
function getInitialRoute(): string {
  return isPublicDemoBuild() || localStorage.getItem("flinttrade:settings") ? "/terminal" : "/welcome";
}

function LegacyAppRedirect() {
  const location = useLocation();
  const app = appForPath(location.pathname) ?? "terminal";
  const openWidget = location.pathname === "/ai" ? { widgetId: "ai-centre" } : location.pathname === "/admin/observability" ? { widgetId: "observability" } : location.pathname === "/admin" ? { widgetId: "system-console" } : undefined;
  return <Navigate to={appPath(app) + location.search + location.hash} state={openWidget ? { openWidget } : location.state} replace />;
}

const router = createBrowserRouter([
  {
    path: "/",
    element: <RootLayout />,
    children: [
      /* One installed entry; no persona selection */
      { index: true, element: <Navigate to={getInitialRoute()} replace /> },

      /* Flow routes -- no chrome (TopBar/TickerBar) */
      { path: "welcome", element: isPublicDemoBuild() ? <Navigate to="/terminal" replace /> : <RouteErrorBoundary routeName="Welcome"><Suspense fallback={<Loading />}><WelcomeRoute /></Suspense></RouteErrorBoundary> },
      ...PUBLIC_ENTRY_REDIRECTS.map((alias) => ({
        path: alias.path,
        element: <Navigate to={alias.to} replace />,
      })),
      { path: "explore", element: isPublicDemoBuild() ? <Navigate to="/terminal" replace /> : <ExplorePathElement /> },
      /* Canonical setup owns account creation and onboarding. The historical
         /setup-account URL remains an explicit compatibility alias. Public demo
         builds send both paths to Explore before any setup UI can mount. */
      { path: CANONICAL_SETUP_PATH.slice(1), element: isPublicDemoBuild() ? <Navigate to="/explore" replace /> : <RouteErrorBoundary routeName="Setup"><Suspense fallback={<Loading />}><CanonicalSetupRoute /></Suspense></RouteErrorBoundary> },
      { path: LEGACY_SETUP_ACCOUNT_PATH.slice(1), element: isPublicDemoBuild() ? <Navigate to="/explore" replace /> : <SetupAccountAlias /> },

      /* App routes -- shared AppLayout chrome (TopBar + TickerBar) */
      {
        element: isPublicDemoBuild() ? <AppLayout /> : <ProtectedRoute><AppLayout /></ProtectedRoute>,
        children: [
          ...APPS.map(app => ({ path: app.path.slice(1), element: <></> })),
          ...["home", "trade", "invest", "lab", "automate", "ai", "ditto", "admin", "admin/observability"].map(path => ({ path, element: <LegacyAppRedirect /> })),
          ...DESK_ROUTE_ALIASES.map(alias => ({ path: alias.path, element: <Navigate to={alias.to} replace /> })),
        ],
      },

      /* 404 catch-all — must be last */
      { path: "*", element: <Suspense fallback={<Loading />}><NotFoundRoute /></Suspense> },
    ],
  },
], {
  // Follow Vite's `base` so subpath hosting works (e.g. the public site
  // serves an Explore-mode build under /demo-app/). The default base "/"
  // must stay "/" — react-router treats basename "" as a non-root prefix
  // and navigate("/") becomes a no-op. Relative bases ("./") cannot be
  // mapped to a router basename, so they fall back to "/".
  basename: import.meta.env.BASE_URL.startsWith("/")
    ? import.meta.env.BASE_URL.replace(/\/+$/, "") || "/"
    : "/",
});

export function mountApplication(MotionProvider: ComponentType<PropsWithChildren<{ reducedMotion: "user" }>>) {
renderReactRoot(
  document.getElementById("root")!,
  <React.StrictMode>
    <ErrorBoundary>
      <JotaiProvider>
        <MotionProvider reducedMotion="user">
          <QueryProvider>
            <RouterProvider router={router} />
          </QueryProvider>
        </MotionProvider>
      </JotaiProvider>
    </ErrorBoundary>
  </React.StrictMode>,
);

}
