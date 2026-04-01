/**
 * BrokerDashboardRoute — daily broker reconnect screen.
 *
 * Shown after mode selection during the daily login flow.
 * Lists all connected broker accounts with their connection status.
 *
 * - OpenAlgo-managed brokers show "Managed by OpenAlgo" badge.
 * - Disconnected brokers show a "Connect" button.
 * - "Skip for now" enters the app with brokers disconnected.
 *
 * Not a standalone route — used as a step inside WelcomeRoute.
 */

import { useEffect, useState } from "react";
import {
  CheckCircle2,
  XCircle,
  Loader2,
  ExternalLink,
  Wifi,
  WifiOff,
  ChevronRight,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { LogoIcon } from "@/components/brand/Logo";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface BrokerAccount {
  id: string;
  name: string;
  broker: string;
  status: "connected" | "disconnected" | "loading";
  managed_by_openalgo: boolean;
}

interface BrokerDashboardRouteProps {
  onEnterApp: () => void;
}

// ---------------------------------------------------------------------------
// BrokerCard
// ---------------------------------------------------------------------------

interface BrokerCardProps {
  account: BrokerAccount;
  onConnect: (id: string) => void;
}

function BrokerCard({ account, onConnect }: BrokerCardProps) {
  const isConnected = account.status === "connected";
  const isLoading = account.status === "loading";

  return (
    <div
      className={[
        "flex items-center justify-between rounded-lg border p-4 transition-colors",
        isConnected
          ? "border-profit/30 bg-profit/5"
          : "border-border-default bg-surface-card",
      ].join(" ")}
      role="listitem"
      aria-label={`${account.name} — ${isConnected ? "connected" : "disconnected"}`}
    >
      {/* Left: status icon + account name */}
      <div className="flex items-center gap-3">
        <span aria-hidden="true">
          {isLoading ? (
            <Loader2 className="size-4 text-text-muted animate-spin" />
          ) : isConnected ? (
            <CheckCircle2 className="size-4 text-profit" />
          ) : (
            <XCircle className="size-4 text-loss" />
          )}
        </span>
        <div className="space-y-0.5">
          <p className="text-sm font-medium text-text-primary leading-none">
            {account.name}
          </p>
          <p className="text-xs text-text-muted">{account.broker}</p>
        </div>
      </div>

      {/* Right: OpenAlgo badge or Connect button */}
      <div className="flex items-center gap-2">
        {account.managed_by_openalgo ? (
          <span className="text-xs px-2 py-0.5 rounded-full bg-accent/10 text-accent border border-accent/20 font-medium">
            Managed by OpenAlgo
          </span>
        ) : !isConnected ? (
          <Button
            size="sm"
            variant="outline"
            onClick={() => onConnect(account.id)}
            disabled={isLoading}
            className="gap-1.5 text-xs h-7"
            aria-label={`Connect ${account.name}`}
          >
            {isLoading ? (
              <Loader2 className="size-3 animate-spin" />
            ) : (
              <ExternalLink className="size-3" />
            )}
            Connect
          </Button>
        ) : (
          <span className="text-xs text-profit font-medium flex items-center gap-1">
            <Wifi className="size-3" aria-hidden="true" />
            Live
          </span>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export default function BrokerDashboardRoute({ onEnterApp }: BrokerDashboardRouteProps) {
  const [accounts, setAccounts] = useState<BrokerAccount[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [fetchError, setFetchError] = useState("");

  // Fetch connected broker accounts from FlintTrade backend
  useEffect(() => {
    let cancelled = false;

    async function fetchAccounts() {
      setIsLoading(true);
      setFetchError("");
      try {
        const resp = await fetch("/ft-api/v1/broker/accounts", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({}),
        });
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        const data = await resp.json();
        if (!cancelled) {
          const items: BrokerAccount[] = (data.data?.accounts ?? []).map(
            (a: Partial<BrokerAccount>) => ({
              id: a.id ?? String(Math.random()),
              name: a.name ?? "Unknown",
              broker: a.broker ?? "",
              status: (a.status as BrokerAccount["status"]) ?? "disconnected",
              managed_by_openalgo: a.managed_by_openalgo ?? false,
            }),
          );
          setAccounts(items);
        }
      } catch {
        if (!cancelled) {
          setFetchError("Could not load broker accounts. You can still enter the app.");
        }
      } finally {
        if (!cancelled) setIsLoading(false);
      }
    }

    void fetchAccounts();
    return () => { cancelled = true; };
  }, []);

  async function handleConnect(accountId: string) {
    // Mark as loading
    setAccounts((prev) =>
      prev.map((a) => (a.id === accountId ? { ...a, status: "loading" } : a)),
    );
    try {
      const resp = await fetch("/ft-api/v1/broker/connect", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ account_id: accountId }),
      });
      const data = await resp.json();
      const success = resp.ok && data.data?.status === "connected";
      setAccounts((prev) =>
        prev.map((a) =>
          a.id === accountId
            ? { ...a, status: success ? "connected" : "disconnected" }
            : a,
        ),
      );
    } catch {
      setAccounts((prev) =>
        prev.map((a) =>
          a.id === accountId ? { ...a, status: "disconnected" } : a,
        ),
      );
    }
  }

  const connectedCount = accounts.filter((a) => a.status === "connected").length;
  const allConnected = accounts.length > 0 && connectedCount === accounts.length;

  return (
    <div className="flex items-center justify-center min-h-screen bg-surface-base p-6">
      <div className="w-full max-w-md space-y-8">

        {/* Header */}
        <div className="flex flex-col items-center gap-3 text-center">
          <LogoIcon size={36} />
          <div>
            <h1 className="font-heading font-bold text-xl text-text-primary">
              Broker Accounts
            </h1>
            <p className="text-sm text-text-muted mt-1">
              Reconnect your brokers to start trading.
            </p>
          </div>
        </div>

        {/* Status summary */}
        {!isLoading && accounts.length > 0 && (
          <div className="flex items-center justify-center gap-1.5 text-xs text-text-secondary">
            {allConnected ? (
              <>
                <CheckCircle2 className="size-3.5 text-profit" aria-hidden="true" />
                All brokers connected
              </>
            ) : (
              <>
                <WifiOff className="size-3.5 text-text-muted" aria-hidden="true" />
                {connectedCount} of {accounts.length} connected
              </>
            )}
          </div>
        )}

        {/* Accounts list */}
        <div className="space-y-2" role="list" aria-label="Broker accounts">
          {isLoading ? (
            <div className="flex items-center justify-center py-8 text-text-muted gap-2">
              <Loader2 className="size-4 animate-spin" aria-hidden="true" />
              <span className="text-sm">Loading accounts…</span>
            </div>
          ) : fetchError ? (
            <div className="p-4 rounded-lg bg-amber-500/10 border border-amber-500/20 text-xs text-amber-400">
              {fetchError}
            </div>
          ) : accounts.length === 0 ? (
            <div className="p-6 rounded-lg border border-dashed border-border-default text-center space-y-1">
              <p className="text-sm text-text-muted">No broker accounts configured.</p>
              <p className="text-xs text-text-muted">
                Set up brokers later in Settings → Broker Accounts.
              </p>
            </div>
          ) : (
            accounts.map((account) => (
              <BrokerCard
                key={account.id}
                account={account}
                onConnect={handleConnect}
              />
            ))
          )}
        </div>

        {/* Actions */}
        <div className="space-y-3">
          {allConnected ? (
            <Button onClick={onEnterApp} className="w-full gap-2" size="lg">
              Enter FlintTrade
              <ChevronRight className="size-4" />
            </Button>
          ) : (
            <>
              {accounts.length > 0 && connectedCount > 0 && (
                <Button onClick={onEnterApp} className="w-full gap-2" size="lg">
                  Enter FlintTrade
                  <ChevronRight className="size-4" />
                </Button>
              )}
              <button
                type="button"
                onClick={onEnterApp}
                className="w-full text-sm text-text-muted hover:text-text-primary transition-colors py-2"
                aria-label="Skip broker connection and enter the app"
              >
                Skip for now — enter app with brokers disconnected
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
