import React, { lazy, Suspense } from "react";
import ReactDOM from "react-dom/client";
import { createBrowserRouter, RouterProvider, Navigate } from "react-router-dom";
import { Provider as JotaiProvider } from "jotai";
import { QueryProvider } from "./providers/QueryProvider";
import RootLayout from "./routes/RootLayout";
import "./index.css";

const TerminalRoute = lazy(() => import("./routes/TerminalRoute"));
const SetupRoute = lazy(() => import("./routes/SetupRoute"));
const InvestRoute = lazy(() => import("./routes/InvestRoute"));
const LearnRoute = lazy(() => import("./routes/LearnRoute"));

const Loading = () => (
  <div className="min-h-screen bg-surface-base flex items-center justify-center">
    <div className="text-text-muted text-sm">Loading...</div>
  </div>
);

const router = createBrowserRouter([
  {
    path: "/",
    element: <RootLayout />,
    children: [
      { index: true, element: <Navigate to="/terminal" replace /> },
      { path: "terminal", element: <Suspense fallback={<Loading />}><TerminalRoute /></Suspense> },
      { path: "setup", element: <Suspense fallback={<Loading />}><SetupRoute /></Suspense> },
      { path: "invest", element: <Suspense fallback={<Loading />}><InvestRoute /></Suspense> },
      { path: "learn", element: <Suspense fallback={<Loading />}><LearnRoute /></Suspense> },
    ],
  },
]);

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <JotaiProvider>
      <QueryProvider>
        <RouterProvider router={router} />
      </QueryProvider>
    </JotaiProvider>
  </React.StrictMode>
);
