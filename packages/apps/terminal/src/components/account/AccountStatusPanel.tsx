/**
 * AccountStatusPanel — the Account Manager's connected-brokers + daily-reauth
 * surface.
 *
 * Polls GET /ft-api/api/v1/accounts/status, which merges OpenAlgo/Ditto rows
 * with native FlintTrade broker rows and reports connection state + whether the
 * broker session is authenticated today / needs re-authentication. Drives the
 * operator to act on any broker that has dropped or needs a daily re-login.
 */

import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { Wifi, WifiOff, ShieldAlert, ShieldCheck } from "lucide-react";
import { get } from "@/services/ftApi";

interface AccountStatus {
  account_id: string;
  source?: "openalgo" | "native";
  broker?: string;
  broker_display?: string;
  name: string;
  enabled: boolean;
  connected: boolean;
  authenticated: boolean;
  needs_reauth: boolean;
  login_retryable?: boolean;
  latency_ms: number;
  error: string;
}

interface StatusResponse {
  accounts: AccountStatus[];
  summary: { total: number; connected: number; authenticated: number; needs_reauth: number };
}

type AuthState = "reauth" | "retry" | "authed" | "unavailable" | "not_authed";

function rowKey(a: AccountStatus): string {
  return `${a.source ?? "openalgo"}:${a.broker ?? "openalgo"}:${a.account_id}`;
}

function reauthHref(a: AccountStatus): string {
  return a.source === "native" ? "/settings#brokers" : "/settings#api";
}

function authState(a: AccountStatus): AuthState {
  if (a.needs_reauth) return "reauth";
  if (a.login_retryable) return "retry";
  if (a.authenticated) return "authed";
  if (!a.enabled) return "unavailable";
  return "not_authed";
}

export function AccountStatusPanel() {
  // `get()` unwraps the backend's `{status, data: {...}}` envelope (parseResponse
  // returns `json.data`), so the resolved value is already `{accounts, summary}`.
  // Reading `data.data.*` here was a second unwrap that left accounts/summary
  // permanently undefined — the panel was stuck on "No broker accounts connected
  // yet." and the re-auth badge + deep-links never rendered.
  const { data, isLoading, isError } = useQuery({
    queryKey: ["accounts", "status"],
    queryFn: () => get<StatusResponse>("accounts/status"),
    refetchInterval: 30_000,
    staleTime: 15_000,
  });

  const accounts = data?.accounts ?? [];
  const summary = data?.summary;

  return (
    <section
      aria-label="Broker connection status"
      className="rounded-lg border border-border-default bg-surface-card p-4 space-y-3"
    >
      <div className="flex items-center justify-between gap-2">
        <h3 className="text-sm font-heading font-semibold text-text-primary">
          Broker connections &amp; reauth
        </h3>
        {summary && summary.needs_reauth > 0 && (
          <span className="inline-flex items-center gap-1 rounded border border-warning/30 bg-warning/10 px-2 py-0.5 text-xxs font-medium text-warning">
            <ShieldAlert size={11} /> {summary.needs_reauth} need re-auth
          </span>
        )}
      </div>

      {isLoading && <p className="text-xs text-text-muted">Checking broker connections…</p>}
      {isError && (
        <p className="text-xs text-text-muted">Account status is unavailable right now.</p>
      )}

      {!isLoading && !isError && accounts.length === 0 && (
        <p className="text-xs text-text-muted">No broker accounts connected yet.</p>
      )}

      {accounts.length > 0 && (
        <ul className="space-y-1.5">
          {accounts.map((a) => {
            const state = authState(a);
            return (
              <li
                key={rowKey(a)}
                className="flex items-center justify-between gap-3 rounded border border-border-default bg-surface-base px-3 py-2"
              >
                <div className="min-w-0">
                  <p className="text-xs font-medium text-text-primary truncate">
                    {a.name || a.account_id}
                  </p>
                  {(a.broker_display || a.source) && (
                    <p className="text-xxs text-text-muted truncate">
                      {a.broker_display ?? "OpenAlgo bridge"}
                      {a.source ? ` · ${a.source === "native" ? "Native" : "OpenAlgo"}` : ""}
                    </p>
                  )}
                  {a.error && <p className="text-xxs text-text-muted truncate">{a.error}</p>}
                </div>
                <div className="flex items-center gap-2 shrink-0">
                  {a.connected ? (
                    <span className="inline-flex items-center gap-1 text-xxs text-profit">
                      <Wifi size={11} /> Online
                    </span>
                  ) : (
                    <span className="inline-flex items-center gap-1 text-xxs text-loss">
                      <WifiOff size={11} /> Offline
                    </span>
                  )}
                  {state === "reauth" ? (
                    // Actionable: deep-link to the Broker Gateway settings where the
                    // operator re-authenticates — the panel must DRIVE the action,
                    // not just report it.
                    <Link
                      to={reauthHref(a)}
                      aria-label={`Re-authenticate ${a.name || a.account_id}`}
                      className="inline-flex items-center gap-1 rounded border border-warning/30 bg-warning/10 px-1.5 py-0.5 text-xxs font-medium text-warning transition-colors hover:bg-warning/20 hover:border-warning/50"
                    >
                      <ShieldAlert size={10} /> Re-auth
                    </Link>
                  ) : state === "retry" ? (
                    <span className="inline-flex items-center gap-1 rounded border border-warning/30 bg-warning/10 px-1.5 py-0.5 text-xxs font-medium text-warning">
                      <ShieldAlert size={10} /> Retry later
                    </span>
                  ) : state === "authed" ? (
                    <span className="inline-flex items-center gap-1 text-xxs text-profit">
                      <ShieldCheck size={11} /> Authed
                    </span>
                  ) : (
                    <span className="inline-flex items-center gap-1 text-xxs text-text-muted">
                      <ShieldAlert size={11} /> {state === "unavailable" ? "Unavailable" : "Not authed"}
                    </span>
                  )}
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
