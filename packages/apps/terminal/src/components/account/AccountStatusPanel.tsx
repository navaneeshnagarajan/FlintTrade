/**
 * AccountStatusPanel — the Account Manager's connected-brokers + daily-reauth
 * surface.
 *
 * Polls GET /ft-api/api/v1/accounts/status, which live-pings each account's
 * OpenAlgo and reports connection state + whether the broker session is
 * authenticated today / needs re-authentication. Drives the operator to act on
 * any broker that has dropped or needs a daily re-login.
 */

import { useQuery } from "@tanstack/react-query";
import { Wifi, WifiOff, ShieldAlert, ShieldCheck } from "lucide-react";
import { get } from "@/services/ftApi";

interface AccountStatus {
  account_id: string;
  name: string;
  enabled: boolean;
  connected: boolean;
  authenticated: boolean;
  needs_reauth: boolean;
  latency_ms: number;
  error: string;
}

interface StatusResponse {
  data: {
    accounts: AccountStatus[];
    summary: { total: number; connected: number; authenticated: number; needs_reauth: number };
  };
}

export function AccountStatusPanel() {
  const { data, isLoading, isError } = useQuery({
    queryKey: ["accounts", "status"],
    queryFn: () => get<StatusResponse>("accounts/status"),
    refetchInterval: 30_000,
    staleTime: 15_000,
  });

  const accounts = data?.data?.accounts ?? [];
  const summary = data?.data?.summary;

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
          {accounts.map((a) => (
            <li
              key={a.account_id}
              className="flex items-center justify-between gap-3 rounded border border-border-default bg-surface-base px-3 py-2"
            >
              <div className="min-w-0">
                <p className="text-xs font-medium text-text-primary truncate">
                  {a.name || a.account_id}
                </p>
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
                {a.needs_reauth ? (
                  <span className="inline-flex items-center gap-1 rounded border border-warning/30 bg-warning/10 px-1.5 py-0.5 text-xxs font-medium text-warning">
                    <ShieldAlert size={10} /> Re-auth
                  </span>
                ) : (
                  <span className="inline-flex items-center gap-1 text-xxs text-profit">
                    <ShieldCheck size={11} /> Authed
                  </span>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
