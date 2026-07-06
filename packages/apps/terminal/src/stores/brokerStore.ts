import { create } from "zustand";
import { devtools, persist } from "zustand/middleware";
import type { BrokerAccount } from "@/types/broker";

type BrokerAccountIdentity = Pick<BrokerAccount, "account_id" | "broker" | "source">;

export function brokerAccountKey(account: BrokerAccountIdentity): string {
  return [
    account.source ?? "gateway",
    account.broker,
    account.account_id,
  ].map(encodeURIComponent).join(":");
}

export function isBrokerAccountMatch(account: BrokerAccountIdentity, selector: string | null): boolean {
  if (!selector) return false;
  return brokerAccountKey(account) === selector || account.account_id === selector;
}

export function findBrokerAccountMatch<T extends BrokerAccountIdentity>(
  accounts: T[],
  selector: string | null,
): T | undefined {
  if (!selector) return undefined;

  const exact = accounts.find((account) => brokerAccountKey(account) === selector);
  if (exact) return exact;

  const legacy = accounts.filter((account) => account.account_id === selector);
  return legacy.length === 1 ? legacy[0] : undefined;
}

/**
 * Persist migration for the broker store.
 *
 * v0 (pre-composite-key builds) persisted `activeAccountId` as a BARE
 * account_id. Because {@link isBrokerAccountMatch} also matches on account_id
 * alone, a rehydrated bare id can first-match a same-id row of the WRONG source
 * (e.g. a gateway row for a dual-linked account), making native write-targeting
 * resolve the wrong account and silently bypass the live-order fail-closed
 * guard. Drop any legacy `activeAccountId` that is not a recognised composite
 * key (`source:broker:account_id`) — the live poll repopulates accounts and the
 * operator re-selects safely.
 */
export function migrateBrokerPersist(persistedState: unknown, version: number): unknown {
  if (version < 1 && persistedState && typeof persistedState === "object") {
    const state = persistedState as { activeAccountId?: unknown };
    const active = state.activeAccountId;
    if (
      typeof active === "string"
      && active.length > 0
      && !active.startsWith("native:")
      && !active.startsWith("gateway:")
    ) {
      return { ...state, activeAccountId: null };
    }
  }
  return persistedState;
}

interface BrokerState {
  accounts: BrokerAccount[];
  activeAccountId: string | null;

  setAccounts: (accounts: BrokerAccount[]) => void;
  addAccount: (account: BrokerAccount) => void;
  removeAccount: (accountId: string) => void;
  updateAccount: (accountId: string, updates: Partial<BrokerAccount>) => void;
  setActiveAccount: (accountId: string) => void;
  getPrimaryAccount: () => BrokerAccount | undefined;
  getActiveAccount: () => BrokerAccount | undefined;
}

export const useBrokerStore = create<BrokerState>()(
  devtools(
    persist(
      (set, get) => ({
        accounts: [],
        activeAccountId: null,

        setAccounts: (accounts) =>
          set((state) => ({
            accounts,
            activeAccountId: findBrokerAccountMatch(accounts, state.activeAccountId)
              ? state.activeAccountId
              : null,
          })),

        addAccount: (account) =>
          set((state) => ({ accounts: [...state.accounts, account] })),

        removeAccount: (accountId) =>
          set((state) => ({
            accounts: state.accounts.filter((a) => !isBrokerAccountMatch(a, accountId)),
            activeAccountId:
              state.accounts.some((a) => (
                isBrokerAccountMatch(a, accountId) && isBrokerAccountMatch(a, state.activeAccountId)
              ))
                ? null
                : state.activeAccountId,
          })),

        updateAccount: (accountId, updates) =>
          set((state) => ({
            accounts: state.accounts.map((a) =>
              isBrokerAccountMatch(a, accountId) ? { ...a, ...updates } : a,
            ),
          })),

        setActiveAccount: (accountId) => set({ activeAccountId: accountId }),

        getPrimaryAccount: () => get().accounts.find((a) => a.is_primary),

        getActiveAccount: () => {
          const { accounts, activeAccountId } = get();
          return findBrokerAccountMatch(accounts, activeAccountId);
        },
      }),
      {
        name: "flinttrade:brokers",
        version: 1,
        migrate: migrateBrokerPersist,
        // Only persist non-sensitive display fields. Credentials and session
        // tokens must never be written to localStorage.
        partialize: (state) => ({
          accounts: state.accounts.map((a) => ({
            account_id: a.account_id,
            broker: a.broker,
            label: a.label,
            is_primary: a.is_primary,
            // Status is deliberately NOT persisted as-is: a removed or expired
            // account must not survive a reload as a "connected" write target.
            // It is re-derived from the live poll (useBrokerAccounts, mounted in
            // AppLayout) within one refresh; until then it reads disconnected so
            // native write-targeting never trusts stale localStorage state.
            status: "disconnected" as BrokerAccount["status"],
            connected_at: a.connected_at,
            error_message: a.error_message,
            source: a.source,
          })),
          activeAccountId: state.activeAccountId,
        }),
      },
    ),
    { name: "BrokerStore" },
  ),
);
