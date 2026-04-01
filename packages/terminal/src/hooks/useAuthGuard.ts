/**
 * Auth guard hook — checks session status on mount and redirects to login.
 *
 * Usage: call at the top of every protected route component.
 * Returns { isAuthenticated, isLoading } so the route can show a loader.
 */

import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuthStore } from "@/stores/authStore";

export function useAuthGuard(): { isAuthenticated: boolean; isLoading: boolean } {
  const navigate = useNavigate();
  const status = useAuthStore((s) => s.status);
  const [isLoading, setIsLoading] = useState(status === "unknown");

  useEffect(() => {
    if (status === "unknown") {
      // Check backend for setup status
      fetch("/ft-api/v1/auth/status")
        .then((r) => {
          if (!r.ok) throw new Error(`HTTP ${r.status}`);
          return r.json();
        })
        .then((data) => {
          if (!data.data?.is_setup) {
            useAuthStore.getState().setSetupRequired();
          } else {
            useAuthStore.getState().setLoggedOut();
          }
          setIsLoading(false);
        })
        .catch(() => {
          // Backend unreachable — in dev mode, allow access without auth
          // so developers can work on the UI without running the Flask server.
          // In production builds, this still redirects to welcome.
          if (import.meta.env.DEV) {
            console.warn("[AuthGuard] Backend unreachable — dev mode bypass active");
            useAuthStore.getState().setLoggedIn("dev-bypass", "developer", "");
          } else {
            useAuthStore.getState().setSetupRequired();
          }
          setIsLoading(false);
        });
      return;
    }

    if (status === "setup-required") {
      navigate("/welcome", { replace: true });
    } else if (status === "logged-out") {
      navigate("/welcome", { replace: true });
    } else if (status === "pin-required") {
      navigate("/welcome", { replace: true });
    }
  }, [status, navigate]);

  return {
    isAuthenticated: status === "logged-in",
    isLoading,
  };
}
