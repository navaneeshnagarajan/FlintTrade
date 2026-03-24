import { create } from "zustand";
import { devtools, persist } from "zustand/middleware";
import type { BrokerAccount } from "@/types/broker";

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

        setAccounts: (accounts) => set({ accounts }),

        addAccount: (account) =>
          set((state) => ({ accounts: [...state.accounts, account] })),

        removeAccount: (accountId) =>
          set((state) => ({
            accounts: state.accounts.filter((a) => a.account_id !== accountId),
            activeAccountId:
              state.activeAccountId === accountId ? null : state.activeAccountId,
          })),

        updateAccount: (accountId, updates) =>
          set((state) => ({
            accounts: state.accounts.map((a) =>
              a.account_id === accountId ? { ...a, ...updates } : a,
            ),
          })),

        setActiveAccount: (accountId) => set({ activeAccountId: accountId }),

        getPrimaryAccount: () => get().accounts.find((a) => a.is_primary),

        getActiveAccount: () => {
          const { accounts, activeAccountId } = get();
          return accounts.find((a) => a.account_id === activeAccountId);
        },
      }),
      { name: "flinttrade:brokers" },
    ),
    { name: "BrokerStore" },
  ),
);
