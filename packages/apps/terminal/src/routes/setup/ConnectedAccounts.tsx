/**
 * ConnectedAccounts — displays all connected broker accounts with status
 * badges and action buttons (set primary, reconnect, remove).
 *
 * Triggers polling via useBrokerAccounts; reads account list from
 * brokerStore (Zustand) as the single source of truth.
 */

import { useState } from "react";
import { Trash2, RefreshCw, Star } from "lucide-react";
import { useBrokerAccounts } from "@/hooks/useBrokerAccounts";
import { brokerAccountKey, useBrokerStore } from "@/stores/brokerStore";
import { gatewayApi } from "@/services/gatewayApi";
import { removeNativeAccount, reloginNativeAccount, setPrimaryNativeAccount } from "@/services/ftApi.native";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import type { BrokerAccount, AccountStatus } from "@/types/broker";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function statusColor(status: AccountStatus): string {
  switch (status) {
    case "connected":
      return "bg-green-500/20 text-green-400 border-green-500/30";
    case "error":
    case "token_expired":
      return "bg-red-500/20 text-red-400 border-red-500/30";
    case "authenticating":
      return "bg-yellow-500/20 text-yellow-400 border-yellow-500/30";
    default:
      return "bg-surface-base text-text-secondary border-border-default";
  }
}

function statusLabel(status: AccountStatus): string {
  switch (status) {
    case "token_expired":
      return "Token Expired";
    default:
      return status.charAt(0).toUpperCase() + status.slice(1);
  }
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function ConnectedAccounts() {
  // Trigger polling — UI reads from store (single source of truth)
  const accountsQuery = useBrokerAccounts();
  const accounts = useBrokerStore((s) => s.accounts);
  const [error, setError] = useState<string | null>(null);

  if (accounts.length === 0) {
    return (
      <div className="text-center py-8 text-text-secondary">
        <p className="text-sm">No broker accounts connected</p>
        <p className="text-xs mt-1 text-text-muted">
          Click &ldquo;Add Account&rdquo; to connect your first broker
        </p>
      </div>
    );
  }

  const refreshAccounts = async () => {
    await accountsQuery.refetch();
  };

  const handleRemove = async (account: BrokerAccount) => {
    try {
      setError(null);
      if (account.source === "native") {
        await removeNativeAccount(account.broker, account.account_id);
      } else {
        await gatewayApi.removeAccount(account.account_id);
      }
      await refreshAccounts();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to remove account");
    }
  };

  const handleReconnect = async (account: BrokerAccount) => {
    try {
      setError(null);
      if (account.source === "native") {
        await reloginNativeAccount(account.broker, account.account_id);
      } else {
        await gatewayApi.reconnectAccount(account.account_id);
      }
      await refreshAccounts();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to reconnect account");
    }
  };

  const handleSetPrimary = async (account: BrokerAccount) => {
    try {
      setError(null);
      if (account.source === "native") {
        await setPrimaryNativeAccount(account.broker, account.account_id);
      } else {
        await gatewayApi.setPrimary(account.account_id);
      }
      await refreshAccounts();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to set primary account");
    }
  };

  return (
    <div className="space-y-2">
      {error && (
        <p className="text-xs text-red-400 px-1 py-1.5 rounded-md bg-red-500/10 border border-red-500/20">
          {error}
        </p>
      )}
      {accounts.map((acct: BrokerAccount) => (
        <div
          key={brokerAccountKey(acct)}
          className="flex items-center justify-between p-3 rounded-lg border border-border-default bg-surface-card"
        >
          <div className="flex items-center gap-3">
            {acct.is_primary && (
              <Star
                className="w-4 h-4 text-accent fill-accent shrink-0"
                aria-label="Primary account"
              />
            )}
            <div className="min-w-0">
              <p className="font-medium text-sm text-text-primary truncate">{acct.label}</p>
              <p className="text-xs text-text-secondary capitalize">{acct.broker}</p>
              {acct.error_message && (
                <p className="text-xs text-red-400 mt-0.5 truncate" title={acct.error_message}>
                  {acct.error_message}
                </p>
              )}
            </div>
          </div>

          <div className="flex items-center gap-2 shrink-0 ml-3">
            <Badge className={statusColor(acct.status)}>{statusLabel(acct.status)}</Badge>

            {!acct.is_primary && (acct.source !== "native" || acct.status === "connected") && (
              <Button
                variant="ghost"
                size="sm"
                onClick={() => void handleSetPrimary(acct)}
                aria-label={`Set ${acct.label} as primary account`}
                title="Set as primary"
              >
                <Star className="w-3.5 h-3.5" />
              </Button>
            )}

            <Button
              variant="ghost"
              size="sm"
              onClick={() => void handleReconnect(acct)}
              aria-label={`Reconnect ${acct.label}`}
              title="Reconnect"
            >
              <RefreshCw className="w-3.5 h-3.5" />
            </Button>

            <Button
              variant="ghost"
              size="sm"
              onClick={() => void handleRemove(acct)}
              aria-label={`Remove ${acct.label}`}
              title="Remove account"
            >
              <Trash2 className="w-3.5 h-3.5 text-red-400" />
            </Button>
          </div>
        </div>
      ))}
    </div>
  );
}
