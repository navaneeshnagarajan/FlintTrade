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
            activeAccountId: accounts.some((account) => isBrokerAccountMatch(account, state.activeAccountId))
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
          return accounts.find((a) => isBrokerAccountMatch(a, activeAccountId));
        },
      }),
      {
        name: "flinttrade:brokers",
        // Only persist non-sensitive display fields. Credentials and session
        // tokens must never be written to localStorage.
        partialize: (state) => ({
          accounts: state.accounts.map((a) => ({
            account_id: a.account_id,
            broker: a.broker,
            label: a.label,
            is_primary: a.is_primary,
            // Persist status so the UI can show last-known state on reload;
            // it will be refreshed from the backend immediately.
            status: a.status,
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
