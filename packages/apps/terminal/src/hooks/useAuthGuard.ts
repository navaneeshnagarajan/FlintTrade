/**
 * Auth guard hook — checks session status on mount and redirects to login.
 *
 * Usage: call at the top of every protected route component.
 * Returns { isAuthenticated, isLoading } so the route can show a loader.
 */

import { useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { isDemoSessionActive } from "@/lib/demoSession";
import {
  captureAuthSessionFence,
  isAuthSessionFenceCurrent,
  useAuthStore,
} from "@/stores/authStore";
import { AuthStatusSchema } from "@/lib/schemas/ftApi";
import { buildHeaders, getBase } from "@/services/ftApi.helpers";

export function useAuthGuard(): {
  isAuthenticated: boolean;
  isLoading: boolean;
} {
  const navigate = useNavigate();
  const status = useAuthStore((s) => s.status);

  useEffect(() => {
    if (status === "unknown") {
      const probeFence = captureAuthSessionFence();
      if (isDemoSessionActive()) {
        useAuthStore
          .getState()
          .setLoggedInIfCurrent("demo-user", "Explorer", "", probeFence);
        return;
      }

      // Check backend for setup status
      fetch(`${getBase()}/v1/auth/status`, { headers: buildHeaders(false) })
        .then((r) => {
          if (!r.ok) throw new Error(`HTTP ${r.status}`);
          return r.json();
        })
        .then((raw: unknown) => {
          if (!isAuthSessionFenceCurrent(probeFence)) return;
          const result = AuthStatusSchema.safeParse(raw);
          if (!result.success) {
            console.error(
              "[AuthGuard] Unexpected /auth/status shape:",
              result.error.issues,
            );
          }
          const data = result.success ? result.data : undefined;
          if (!data?.data?.is_setup) {
            useAuthStore.getState().setSetupRequired();
          } else {
            useAuthStore.getState().setLoggedOut();
          }
        })
        .catch(() => {
          if (!isAuthSessionFenceCurrent(probeFence)) return;
          // Backend unreachable — in dev mode, allow access without auth
          // so developers can work on the UI without running the Flask server.
          // In production builds, this still redirects to welcome.
          if (import.meta.env.DEV) {
            console.warn(
              "[AuthGuard] Backend unreachable — dev mode bypass active",
            );
            useAuthStore
              .getState()
              .setLoggedInIfCurrent("dev-bypass", "developer", "", probeFence);
          } else {
            useAuthStore.getState().setSetupRequired();
          }
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
    // Status is the source of truth, so a competing auth transition clears
    // the loader without waiting for an obsolete probe to settle.
    isLoading: status === "unknown",
  };
}
