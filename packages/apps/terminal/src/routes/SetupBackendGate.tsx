import { useEffect, useRef, useState, type ReactNode } from "react";
import { AlertTriangle, RefreshCw } from "lucide-react";
import { Link } from "react-router";

import { Button } from "@/components/ui/button";
import { getBase } from "@/services/ftApi.helpers";

const BACKEND_PROBE_TIMEOUT_MS = 6_000;

type BackendState = "checking" | "available" | "unavailable" | "busy" | "error";

interface ProbeFailure {
  reason: "network" | "busy" | "http";
  status?: number;
}

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

async function probeSetupBackend(signal: AbortSignal): Promise<ProbeFailure | null> {
  let response: Response;
  try {
    response = await fetch(`${getBase()}/v1/auth/status`, {
      method: "GET",
      headers: { Accept: "application/json" },
      cache: "no-store",
      signal,
    });
  } catch {
    return { reason: "network" };
  }
  if (response.status === 429) return { reason: "busy", status: 429 };
  let payload: unknown = null;
  try {
    payload = await response.json();
  } catch {
    payload = null;
  }
  if (!response.ok || !isSetupStatusPayload(payload)) {
    return { reason: "http", status: response.status };
  }
  return null;
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
  const [httpStatus, setHttpStatus] = useState<number | null>(null);
  const alertRef = useRef<HTMLElement>(null);

  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    const timeout = window.setTimeout(() => controller.abort(), BACKEND_PROBE_TIMEOUT_MS);

    setBackendState("checking");
    setHttpStatus(null);
    void probeSetupBackend(controller.signal)
      .then((failure) => {
        if (!active) return;
        if (!failure) {
          setBackendState("available");
          return;
        }
        setHttpStatus(failure.status ?? null);
        if (failure.reason === "network") setBackendState("unavailable");
        else if (failure.reason === "busy") setBackendState("busy");
        else setBackendState("error");
      })
      .finally(() => window.clearTimeout(timeout));

    return () => {
      active = false;
      window.clearTimeout(timeout);
      controller.abort();
    };
  }, [attempt]);

  useEffect(() => {
    if (backendState === "unavailable" || backendState === "busy" || backendState === "error") {
      alertRef.current?.focus();
    }
  }, [backendState]);

  if (backendState === "available") return <>{children}</>;

  if (backendState === "busy" || backendState === "error") {
    const busy = backendState === "busy";
    const title = busy ? "Setup is busy" : "Setup status could not be read";
    const detail = busy
      ? "The server is busy. Retry in a moment. Setup has not advanced."
      : `The server could not check setup (HTTP ${httpStatus ?? "error"}). Retry. Setup has not advanced.`;
    return (
      <main
        aria-label="Account setup"
        className="flex min-h-screen items-center justify-center bg-surface-base px-4 text-text-primary"
      >
        <section
          ref={alertRef}
          role="alert"
          aria-live="assertive"
          aria-labelledby="setup-status-error-title"
          tabIndex={-1}
          className="w-full max-w-lg rounded-xl border border-amber-500/30 bg-surface-card p-6 text-left shadow-2xl outline-none focus-visible:ring-2 focus-visible:ring-accent"
        >
          <div className="flex items-start gap-3">
            <AlertTriangle className="mt-0.5 size-5 shrink-0 text-amber-400" aria-hidden="true" />
            <div className="space-y-2">
              <h1 id="setup-status-error-title" className="font-heading text-xl font-bold">
                {title}
              </h1>
              <p className="text-sm leading-relaxed text-text-secondary">{detail}</p>
            </div>
          </div>
          <div className="mt-5 flex flex-wrap gap-3">
            <Button type="button" onClick={() => setAttempt((value) => value + 1)}>
              <RefreshCw className="mr-2 size-4" aria-hidden="true" />
              Retry
            </Button>
            <Button asChild variant="outline">
              <Link to="/welcome">Return to welcome</Link>
            </Button>
          </div>
        </section>
      </main>
    );
  }

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
