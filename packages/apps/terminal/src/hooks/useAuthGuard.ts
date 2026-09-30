/**
 * Auth guard hook — checks session status on mount and redirects to login.
 *
 * Usage: call at the top of every protected route component.
 * Returns { isAuthenticated, isLoading } so the route can show a loader.
 */

import { useEffect } from "react";
import { useLocation, useNavigate } from "react-router";
import { EXAMPLE_USER_DISPLAY_NAME, isDemoSessionActive } from "@/lib/demoSession";
import { decideHomeEntry, readPersistedAuthSession, WELCOME_GATE_PATH } from "@/lib/homeEntry";
import {
  isTwoOperatorGuideLocation,
  migrationBlockedFromStatus,
} from "@/lib/twoOperatorGuide";
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
  const location = useLocation();
  const status = useAuthStore((s) => s.status);
  const guideOnly = isTwoOperatorGuideLocation(location);

  useEffect(() => {
    if (guideOnly) return;
    if (status === "unknown") {
      const probeFence = captureAuthSessionFence();
      const persisted = readPersistedAuthSession();
      if (persisted) {
        fetch(`${getBase()}/v1/auth/status`, { headers: buildHeaders(false) })
          .then((response) => {
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            return response.json() as Promise<unknown>;
          })
          .then((raw: unknown) => {
            if (!isAuthSessionFenceCurrent(probeFence)) return;
            if (migrationBlockedFromStatus(raw)) {
              navigate(WELCOME_GATE_PATH, { replace: true });
              return;
            }
            useAuthStore
              .getState()
              .setLoggedInIfCurrent(
                persisted.token,
                persisted.username,
                persisted.expiresAt,
                probeFence,
              );
          })
          .catch(() => {
            if (!isAuthSessionFenceCurrent(probeFence)) return;
            useAuthStore
              .getState()
              .setLoggedInIfCurrent(
                persisted.token,
                persisted.username,
                persisted.expiresAt,
                probeFence,
              );
          });
        return;
      }
      if (isDemoSessionActive()) {
        useAuthStore
          .getState()
          .setLoggedInIfCurrent("demo-user", EXAMPLE_USER_DISPLAY_NAME, "", probeFence);
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
          // A late status probe must not clear a hatch session that landed
          // while the request was in flight (setLoggedOut wipes the marker).
          if (isDemoSessionActive()) {
            useAuthStore
              .getState()
              .setLoggedInIfCurrent("demo-user", EXAMPLE_USER_DISPLAY_NAME, "", probeFence);
            return;
          }
          const result = AuthStatusSchema.safeParse(raw);
          if (!result.success) {
            console.error(
              "[AuthGuard] Unexpected /auth/status shape:",
              result.error.issues,
            );
          }
          const data = result.success ? result.data : undefined;
          if (migrationBlockedFromStatus(raw)) {
            navigate(WELCOME_GATE_PATH, { replace: true });
            return;
          }
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

    const entry = decideHomeEntry(status);
    if (entry.kind === "gate") {
      navigate(WELCOME_GATE_PATH, { replace: true });
    }
  }, [guideOnly, status, navigate]);

  return {
    isAuthenticated: status === "logged-in" || guideOnly,
    // Status is the source of truth, so a competing auth transition clears
    // the loader without waiting for an obsolete probe to settle. The
    // troubleshooting guide is not the desk and does not wait on a session.
    isLoading: status === "unknown" && !guideOnly,
  };
}
