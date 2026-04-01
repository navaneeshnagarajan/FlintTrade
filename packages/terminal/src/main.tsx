import React, { lazy, Suspense } from "react";
import ReactDOM from "react-dom/client";
import { createBrowserRouter, RouterProvider, Navigate } from "react-router-dom";
import { Provider as JotaiProvider } from "jotai";
import { MotionConfig } from "framer-motion";
import { QueryProvider } from "./providers/QueryProvider";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { RouteErrorBoundary } from "./components/RouteErrorBoundary";
import RootLayout from "./routes/RootLayout";
import AppLayout from "./routes/AppLayout";
import "./index.css";

const TerminalRoute = lazy(() => import("./routes/TerminalRoute"));
const SetupRoute = lazy(() => import("./routes/SetupRoute"));
const InvestRoute = lazy(() => import("./routes/InvestRoute"));
const LearnRoute = lazy(() => import("./routes/LearnRoute"));
const WelcomeRoute = lazy(() => import("./routes/WelcomeRoute"));
const ExploreRoute = lazy(() => import("./routes/ExploreRoute"));
const LabRoute = lazy(() => import("./routes/LabRoute"));
const AutomateRoute = lazy(() => import("./routes/AutomateRoute"));
const AIRoute = lazy(() => import("./routes/AIRoute"));
const SettingsRoute = lazy(() => import("./routes/SettingsRoute"));
const DittoRoute = lazy(() => import("./routes/DittoRoute"));
const NotFoundRoute = lazy(() => import("./routes/NotFoundRoute"));

function Loading() {
  return (
    <div className="flex items-center justify-center h-screen bg-background" role="status">
      <div className="flex flex-col items-center gap-3">
        <div className="w-8 h-8 border-2 border-accent/30 border-t-accent rounded-full animate-spin" />
        <p className="text-sm text-muted animate-pulse">Loading FlintTrade...</p>
      </div>
    </div>
  );
}

/**
 * Determine the initial route based on persisted settings.
 * First-time users (no settings) go to /welcome.
 * Returning users go to their persona's default route.
 */
function getInitialRoute(): string {
  const raw = localStorage.getItem("flinttrade:settings");
  if (!raw) return "/welcome";
  try {
    const envelope = JSON.parse(raw) as { state?: { persona?: string } };
    const persona = envelope?.state?.persona;
    if (!persona) return "/welcome";
    if (persona === "investor") return "/invest";
    if (persona === "beginner") return "/learn";
    return "/trade";
  } catch {
    return "/welcome";
  }
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
      { path: "explore", element: <RouteErrorBoundary routeName="Explore"><Suspense fallback={<Loading />}><ExploreRoute /></Suspense></RouteErrorBoundary> },
      { path: "setup", element: <RouteErrorBoundary routeName="Setup"><Suspense fallback={<Loading />}><SetupRoute /></Suspense></RouteErrorBoundary> },
      { path: "settings", element: <RouteErrorBoundary routeName="Settings"><Suspense fallback={<Loading />}><SettingsRoute /></Suspense></RouteErrorBoundary> },

      /* App routes -- shared AppLayout chrome (TopBar + TickerBar) */
      {
        element: <AppLayout />,
        children: [
          { path: "trade", element: <RouteErrorBoundary routeName="Trade"><Suspense fallback={<Loading />}><TerminalRoute /></Suspense></RouteErrorBoundary> },
          { path: "terminal", element: <Navigate to="/trade" replace /> },
          { path: "invest", element: <RouteErrorBoundary routeName="Invest"><Suspense fallback={<Loading />}><InvestRoute /></Suspense></RouteErrorBoundary> },
          { path: "learn", element: <RouteErrorBoundary routeName="Learn"><Suspense fallback={<Loading />}><LearnRoute /></Suspense></RouteErrorBoundary> },
          { path: "lab", element: <RouteErrorBoundary routeName="Lab"><Suspense fallback={<Loading />}><LabRoute /></Suspense></RouteErrorBoundary> },
          { path: "automate", element: <RouteErrorBoundary routeName="Automate"><Suspense fallback={<Loading />}><AutomateRoute /></Suspense></RouteErrorBoundary> },
          { path: "ai", element: <RouteErrorBoundary routeName="AI"><Suspense fallback={<Loading />}><AIRoute /></Suspense></RouteErrorBoundary> },
          { path: "ditto", element: <RouteErrorBoundary routeName="Ditto"><Suspense fallback={<Loading />}><DittoRoute /></Suspense></RouteErrorBoundary> },
        ],
      },

      /* Admin dashboard — DEV only */
      ...(import.meta.env.DEV
        ? [{ path: "admin", lazy: () => import("./routes/AdminRoute").then((m) => ({ Component: m.default })) }]
        : []),

      /* 404 catch-all — must be last */
      { path: "*", element: <Suspense fallback={<Loading />}><NotFoundRoute /></Suspense> },
    ],
  },
]);

ReactDOM.createRoot(document.getElementById("root")!).render(
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
  </React.StrictMode>
);
