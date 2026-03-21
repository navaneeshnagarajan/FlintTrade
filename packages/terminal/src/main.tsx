import React, { lazy, Suspense } from "react";
import ReactDOM from "react-dom/client";
import { createBrowserRouter, RouterProvider, Navigate } from "react-router-dom";
import { Provider as JotaiProvider } from "jotai";
import { QueryProvider } from "./providers/QueryProvider";
import { ErrorBoundary } from "./components/ErrorBoundary";
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
const NotFoundRoute = lazy(() => import("./routes/NotFoundRoute"));

const Loading = () => (
  <div className="min-h-screen bg-surface-base flex items-center justify-center">
    <div className="text-text-muted text-sm">Loading...</div>
  </div>
);

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
      { path: "welcome", element: <Suspense fallback={<Loading />}><WelcomeRoute /></Suspense> },
      { path: "explore", element: <Suspense fallback={<Loading />}><ExploreRoute /></Suspense> },
      { path: "setup", element: <Suspense fallback={<Loading />}><SetupRoute /></Suspense> },
      { path: "settings", element: <Suspense fallback={<Loading />}><SettingsRoute /></Suspense> },

      /* App routes -- shared AppLayout chrome (TopBar + TickerBar) */
      {
        element: <AppLayout />,
        children: [
          { path: "trade", element: <Suspense fallback={<Loading />}><TerminalRoute /></Suspense> },
          { path: "terminal", element: <Navigate to="/trade" replace /> },
          { path: "invest", element: <Suspense fallback={<Loading />}><InvestRoute /></Suspense> },
          { path: "learn", element: <Suspense fallback={<Loading />}><LearnRoute /></Suspense> },
          { path: "lab", element: <Suspense fallback={<Loading />}><LabRoute /></Suspense> },
          { path: "automate", element: <Suspense fallback={<Loading />}><AutomateRoute /></Suspense> },
          { path: "ai", element: <Suspense fallback={<Loading />}><AIRoute /></Suspense> },
        ],
      },

      /* 404 catch-all — must be last */
      { path: "*", element: <Suspense fallback={<Loading />}><NotFoundRoute /></Suspense> },
    ],
  },
]);

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <ErrorBoundary>
      <JotaiProvider>
        <QueryProvider>
          <RouterProvider router={router} />
        </QueryProvider>
      </JotaiProvider>
    </ErrorBoundary>
  </React.StrictMode>
);
