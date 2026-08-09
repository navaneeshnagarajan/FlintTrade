import { useEffect, useRef, useState, type ReactNode } from "react";
import { AlertTriangle, RefreshCw } from "lucide-react";
import { Link } from "react-router";

import { Button } from "@/components/ui/button";
import { getBase } from "@/services/ftApi.helpers";

const BACKEND_PROBE_TIMEOUT_MS = 6_000;

type BackendState = "checking" | "available" | "unavailable";

interface SetupBackendGateProps {
  children: ReactNode;
}

function isSetupStatusPayload(value: unknown): boolean {
  if (value === null || typeof value !== "object") return false;
  const data = (value as { data?: unknown }).data;
  return data !== null
    && typeof data === "object"
    && typeof (data as { is_setup?: unknown }).is_setup === "boolean";
}

async function probeSetupBackend(signal: AbortSignal): Promise<void> {
  const response = await fetch(`${getBase()}/v1/auth/status`, {
    method: "GET",
    headers: { Accept: "application/json" },
    cache: "no-store",
    signal,
  });
  if (!response.ok) throw new Error("backend status request failed");
  const payload: unknown = await response.json();
  if (!isSetupStatusPayload(payload)) throw new Error("backend status response was invalid");
}

/**
 * Fail-closed availability boundary for the canonical setup flow.
 *
 * Setup fields do not mount until the public local-backend status probe has
 * returned a valid response. The probe never reads or sends stored credentials.
 */
export function SetupBackendGate({ children }: SetupBackendGateProps) {
  const [attempt, setAttempt] = useState(0);
  const [backendState, setBackendState] = useState<BackendState>("checking");
  const alertRef = useRef<HTMLElement>(null);

  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    const timeout = window.setTimeout(() => controller.abort(), BACKEND_PROBE_TIMEOUT_MS);

    setBackendState("checking");
    void probeSetupBackend(controller.signal)
      .then(() => {
        if (active) setBackendState("available");
      })
      .catch(() => {
        if (active) setBackendState("unavailable");
      })
      .finally(() => window.clearTimeout(timeout));

    return () => {
      active = false;
      window.clearTimeout(timeout);
      controller.abort();
    };
  }, [attempt]);

  useEffect(() => {
    if (backendState === "unavailable") alertRef.current?.focus();
  }, [backendState]);

  if (backendState === "available") return <>{children}</>;

  if (backendState === "checking") {
    return (
      <main
        aria-label="Account setup"
        className="flex min-h-screen items-center justify-center bg-surface-base px-4 text-text-primary"
      >
        <div role="status" aria-live="polite" className="text-center">
          <RefreshCw className="mx-auto mb-3 size-6 animate-spin text-accent" aria-hidden="true" />
          <p className="text-sm text-text-secondary">Checking the local FlintTrade backend…</p>
        </div>
      </main>
    );
  }

  return (
    <main
      aria-label="Account setup unavailable"
      className="flex min-h-screen items-center justify-center bg-surface-base px-4 text-text-primary"
    >
      <section
        ref={alertRef}
        role="alert"
        aria-live="assertive"
        aria-labelledby="setup-backend-unavailable-title"
        tabIndex={-1}
        className="w-full max-w-lg rounded-xl border border-amber-500/30 bg-surface-card p-6 text-left shadow-2xl outline-none focus-visible:ring-2 focus-visible:ring-accent"
      >
        <div className="flex items-start gap-3">
          <AlertTriangle className="mt-0.5 size-5 shrink-0 text-amber-400" aria-hidden="true" />
          <div className="space-y-2">
            <h1 id="setup-backend-unavailable-title" className="font-heading text-xl font-bold">
              FlintTrade backend unavailable
            </h1>
            <p className="text-sm leading-relaxed text-text-secondary">
              Start or restart the local FlintTrade backend, then retry. Setup has not advanced and no
              account, broker, or credential details were submitted from this screen.
            </p>
          </div>
        </div>
        <div className="mt-5 flex flex-wrap gap-3">
          <Button type="button" onClick={() => setAttempt((value) => value + 1)}>
            <RefreshCw className="mr-2 size-4" aria-hidden="true" />
            Retry connection
          </Button>
          <Button asChild variant="outline">
            <Link to="/welcome">Return to welcome</Link>
          </Button>
        </div>
      </section>
    </main>
  );
}
