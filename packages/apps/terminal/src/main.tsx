import React, { lazy, Suspense } from "react";
import { z } from "zod";
import { safeParse } from "./lib/safeParse";
import { getColdStartPath } from "@/lib/personaDefaultRoute";
import { createBrowserRouter, Navigate } from "react-router";
// RouterProvider must come from react-router/dom: the root export is the
// non-DOM variant without ReactDOM.flushSync wiring, so navigate/submit
// flushSync opt-ins would silently degrade to transitions.
import { RouterProvider } from "react-router/dom";
import { Provider as JotaiProvider } from "jotai";
import { MotionConfig } from "framer-motion";
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
    <RouteErrorBoundary routeName="Explore">
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
if (glitchtipDsn) {
  // Dynamic import so the Sentry bundle is excluded entirely when no DSN is set.
  import("@sentry/react").then((Sentry) => {
    Sentry.init({
      dsn: glitchtipDsn,
      integrations: [Sentry.browserTracingIntegration()],
      tracesSampleRate: 0.1,
      environment: import.meta.env.DEV ? "development" : "production",
    });
  }).catch(() => {
    // Silently ignore — error tracking must never break the app.
  });
}

const HomeRoute = lazy(() => import("./routes/HomeRoute"));
const TerminalRoute = lazy(() => import("./routes/TerminalRoute"));
const CanonicalSetupRoute = lazy(() => import("./routes/CanonicalSetupRoute"));
const InvestRoute = lazy(() => import("./routes/InvestRoute"));
const LearnRoute = lazy(() => import("./routes/LearnRoute"));
const WelcomeRoute = lazy(() => import("./routes/WelcomeRoute"));
const ExploreRoute = lazy(() => import("./routes/ExploreRoute"));
const LabRoute = lazy(() => import("./routes/LabRoute"));
const AutomateRoute = lazy(() => import("./routes/AutomateRoute"));
const AIRoute = lazy(() => import("./routes/AIRoute"));
const SettingsRoute = lazy(() => import("./routes/SettingsRoute"));
const DittoRoute = lazy(() => import("./routes/DittoRoute"));
const AdminRoute = lazy(() => import("./routes/AdminRoute"));
const ObservabilityDashboard = lazy(() => import("./admin/observability"));
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
 * Returning users go to their persona's default route.
 */
const settingsEnvelopeSchema = z.object({
  state: z.object({ persona: z.string() }).optional(),
}).optional();

function getInitialRoute(): string {
  const raw = localStorage.getItem("flinttrade:settings");
  if (!raw) return "/welcome";
  const envelope = safeParse(raw, settingsEnvelopeSchema);
  const persona = envelope?.state?.persona;
  const hasSettingsPersona = !!persona;
  return getColdStartPath(persona, hasSettingsPersona);
}

const router = createBrowserRouter([
  {
    path: "/",
    element: <RootLayout />,
    children: [
      /* Smart redirect based on persona */
      { index: true, element: <Navigate to={getInitialRoute()} replace /> },

      /* Flow routes -- no chrome (TopBar/TickerBar) */
      { path: "welcome", element: <RouteErrorBoundary routeName="Welcome"><Suspense fallback={<Loading />}><WelcomeRoute /></Suspense></RouteErrorBoundary> },
      { path: "explore", element: <ExplorePathElement /> },
      /* Canonical setup owns account creation and onboarding. The historical
         /setup-account URL remains an explicit compatibility alias. Public demo
         builds send both paths to Explore before any setup UI can mount. */
      { path: CANONICAL_SETUP_PATH.slice(1), element: isPublicDemoBuild() ? <Navigate to="/explore" replace /> : <RouteErrorBoundary routeName="Setup"><Suspense fallback={<Loading />}><CanonicalSetupRoute /></Suspense></RouteErrorBoundary> },
      { path: LEGACY_SETUP_ACCOUNT_PATH.slice(1), element: isPublicDemoBuild() ? <Navigate to="/explore" replace /> : <SetupAccountAlias /> },

      /* App routes -- shared AppLayout chrome (TopBar + TickerBar) */
      {
        element: <ProtectedRoute><AppLayout /></ProtectedRoute>,
        children: [
          { path: "home", element: <ProtectedRoute><RouteErrorBoundary routeName="Home"><Suspense fallback={<Loading />}><HomeRoute /></Suspense></RouteErrorBoundary></ProtectedRoute> },
          { path: "trade", element: <ProtectedRoute><RouteErrorBoundary routeName="Trade"><Suspense fallback={<Loading />}><TerminalRoute /></Suspense></RouteErrorBoundary></ProtectedRoute> },
          { path: "terminal", element: <Navigate to="/trade" replace /> },
          { path: "invest", element: <ProtectedRoute><RouteErrorBoundary routeName="Invest"><Suspense fallback={<Loading />}><InvestRoute /></Suspense></RouteErrorBoundary></ProtectedRoute> },
          { path: "learn", element: <ProtectedRoute><RouteErrorBoundary routeName="Learn"><Suspense fallback={<Loading />}><LearnRoute /></Suspense></RouteErrorBoundary></ProtectedRoute> },
          { path: "lab", element: <ProtectedRoute><RouteErrorBoundary routeName="Lab"><Suspense fallback={<Loading />}><LabRoute /></Suspense></RouteErrorBoundary></ProtectedRoute> },
          { path: "automate", element: <ProtectedRoute><RouteErrorBoundary routeName="Automate"><Suspense fallback={<Loading />}><AutomateRoute /></Suspense></RouteErrorBoundary></ProtectedRoute> },
          { path: "ai", element: <ProtectedRoute><RouteErrorBoundary routeName="AI"><Suspense fallback={<Loading />}><AIRoute /></Suspense></RouteErrorBoundary></ProtectedRoute> },
          { path: "ditto", element: <ProtectedRoute><RouteErrorBoundary routeName="Account Manager"><Suspense fallback={<Loading />}><DittoRoute /></Suspense></RouteErrorBoundary></ProtectedRoute> },
          { path: "settings", element: <ProtectedRoute><RouteErrorBoundary routeName="Settings"><Suspense fallback={<Loading />}><SettingsRoute /></Suspense></RouteErrorBoundary></ProtectedRoute> },
          ...(import.meta.env.DEV
            ? [
                { path: "admin", element: <ProtectedRoute><RouteErrorBoundary routeName="Admin"><Suspense fallback={<Loading />}><AdminRoute /></Suspense></RouteErrorBoundary></ProtectedRoute> },
                { path: "admin/observability", element: <ProtectedRoute><RouteErrorBoundary routeName="Observability"><Suspense fallback={<Loading />}><ObservabilityDashboard /></Suspense></RouteErrorBoundary></ProtectedRoute> },
              ]
            : []),
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

renderReactRoot(
  document.getElementById("root")!,
  <React.StrictMode>
    <ErrorBoundary>
      <JotaiProvider>
        <MotionConfig reducedMotion="user">
          <QueryProvider>
            <RouterProvider router={router} />
          </QueryProvider>
        </MotionConfig>
      </JotaiProvider>
    </ErrorBoundary>
  </React.StrictMode>,
);
