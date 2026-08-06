/**
 * AccountSwitcher — compact TopBar dropdown for switching active broker accounts.
 *
 * Shows all connected accounts from brokerStore. Clicking an account sets it as
 * the active account and invalidates all TanStack Query caches so fresh data
 * loads for the new account context.
 *
 * Placed between the connection status indicator and market status badge in TopBar.
 */

import { useCallback } from "react";
import { Check, ChevronDown, User } from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";
import { useShallow } from "zustand/react/shallow";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { brokerAccountKey, isBrokerAccountMatch, useBrokerStore } from "@/stores/brokerStore";
import type { AccountStatus, BrokerAccount } from "@/types/broker";

// ---------------------------------------------------------------------------
// Status dot colour
// ---------------------------------------------------------------------------

function statusColor(status: AccountStatus): string {
  switch (status) {
    case "connected":
      return "bg-profit";
    case "authenticating":
      return "bg-amber-400";
    case "error":
    case "token_expired":
      return "bg-loss";
    default:
      return "bg-text-muted";
  }
}

function statusLabel(status: AccountStatus): string {
  switch (status) {
    case "connected":
      return "Connected";
    case "authenticating":
      return "Authenticating";
    case "error":
      return "Error";
    case "token_expired":
      return "Token expired";
    default:
      return "Disconnected";
  }
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function AccountSwitcher() {
  const queryClient = useQueryClient();

  const { accounts, activeAccountId, setActiveAccount } = useBrokerStore(
    useShallow((s) => ({
      accounts: s.accounts,
      activeAccountId: s.activeAccountId,
      setActiveAccount: s.setActiveAccount,
    })),
  );

  const activeAccount = accounts.find((a) => isBrokerAccountMatch(a, activeAccountId));

  const handleSwitch = useCallback(
    (account: BrokerAccount) => {
      if (isBrokerAccountMatch(account, activeAccountId)) return;
      setActiveAccount(brokerAccountKey(account));
      // Invalidate all queries so data refreshes for the new account context
      void queryClient.invalidateQueries();
    },
    [activeAccountId, setActiveAccount, queryClient],
  );

  if (accounts.length === 0) {
    return (
      <span
        className="flex h-7 items-center gap-1 px-2 text-xs text-text-muted"
        aria-label="Broker connectivity: No broker connected"
      >
        <User size={12} aria-hidden="true" />
        No broker connected
      </span>
    );
  }

  const label = activeAccount
    ? `${activeAccount.broker.toUpperCase()} · ${activeAccount.label}`
    : "No account";

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button
          className="flex items-center gap-1 h-7 px-2 rounded text-xs text-text-secondary hover:text-text-primary hover:bg-surface-hover transition-colors"
          aria-label={`Active account: ${label}. Click to switch account.`}
        >
          <User size={12} className="text-text-muted" aria-hidden="true" />
          <span className="max-w-24 truncate font-medium">{label}</span>
          {activeAccount && (
            <span
              className={`w-1.5 h-1.5 rounded-full shrink-0 ${statusColor(activeAccount.status)}`}
              aria-hidden="true"
            />
          )}
          <ChevronDown size={10} className="text-text-muted" aria-hidden="true" />
        </button>
      </DropdownMenuTrigger>

      <DropdownMenuContent align="end" className="w-56">
        <div className="px-2 py-1.5">
          <p className="text-xxs text-text-muted uppercase tracking-wider font-medium">
            Broker Accounts
          </p>
        </div>
        <DropdownMenuSeparator />

        {accounts.map((account) => {
          const key = brokerAccountKey(account);
          const isActive = isBrokerAccountMatch(account, activeAccountId);
          return (
            <DropdownMenuItem
              key={key}
              onClick={() => handleSwitch(account)}
              className="flex items-center justify-between gap-2 cursor-pointer"
            >
              <div className="flex items-center gap-2 min-w-0">
                <span
                  className={`w-1.5 h-1.5 rounded-full shrink-0 ${statusColor(account.status)}`}
                  aria-hidden="true"
                />
                <div className="min-w-0">
                  <p className="text-xs font-medium text-text-primary truncate">
                    {account.broker.toUpperCase()} · {account.label}
                  </p>
                  <p className="text-xxs text-text-muted">
                    {statusLabel(account.status)}
                  </p>
                </div>
              </div>
              {isActive && (
                <Check
                  size={12}
                  className="text-accent shrink-0"
                  aria-label="Active account"
                />
              )}
            </DropdownMenuItem>
          );
        })}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
