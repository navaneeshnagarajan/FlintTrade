/**
 * AccountSwitcher.test.tsx — Renders account dropdown, shows connected accounts.
 */

import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

type MockAccount = {
  account_id: string;
  broker: string;
  label: string;
  status: "connected" | "disconnected";
  connected_at: string | null;
  error_message: string | null;
  source?: "gateway" | "native";
};

const mockAccounts: MockAccount[] = [
  {
    account_id: "acc-1",
    broker: "zerodha",
    label: "Primary",
    status: "connected" as const,
    connected_at: "2026-04-08T09:00:00Z",
    error_message: null,
  },
  {
    account_id: "acc-2",
    broker: "finvasia",
    label: "Secondary",
    status: "disconnected" as const,
    connected_at: null,
    error_message: null,
  },
];

let storeState: { accounts: MockAccount[]; activeAccountId: string | null } = {
  accounts: mockAccounts,
  activeAccountId: "acc-1",
};

vi.mock("@/stores/brokerStore", () => ({
  brokerAccountKey: (account: MockAccount) => [
    account.source ?? "gateway",
    account.broker,
    account.account_id,
  ].map(encodeURIComponent).join(":"),
  isBrokerAccountMatch: (account: MockAccount, selector: string | null) => {
    if (!selector) return false;
    const key = [
      account.source ?? "gateway",
      account.broker,
      account.account_id,
    ].map(encodeURIComponent).join(":");
    return key === selector || account.account_id === selector;
  },
  useBrokerStore: (selector: (s: typeof storeState & { setActiveAccount: () => void }) => unknown) =>
    selector({ ...storeState, setActiveAccount: vi.fn() }),
}));

vi.mock("zustand/react/shallow", () => ({
  useShallow: (fn: unknown) => fn,
}));

// ---------------------------------------------------------------------------
// Import after mocks
// ---------------------------------------------------------------------------

import AccountSwitcher from "../AccountSwitcher";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function renderWithProviders() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <AccountSwitcher />
    </QueryClientProvider>,
  );
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("AccountSwitcher", () => {
  it("renders the active account label in the trigger button", () => {
    storeState = { accounts: mockAccounts, activeAccountId: "acc-1" };
    renderWithProviders();
    expect(screen.getByText("ZERODHA · Primary")).toBeInTheDocument();
  });

  it("keeps zero broker connectivity visible when there are no accounts", () => {
    storeState = { accounts: [], activeAccountId: null };
    renderWithProviders();
    expect(screen.getByText("No broker connected")).toBeInTheDocument();
  });

  it("uses broker-aware active keys when account ids collide", () => {
    storeState = {
      accounts: [
        {
          account_id: "same",
          broker: "dhan",
          label: "Dhan",
          status: "connected",
          connected_at: "2026-04-08T09:00:00Z",
          error_message: null,
          source: "native",
        },
        {
          account_id: "same",
          broker: "upstox",
          label: "Upstox",
          status: "connected",
          connected_at: "2026-04-08T09:00:00Z",
          error_message: null,
          source: "native",
        },
      ],
      activeAccountId: "native:upstox:same",
    };
    renderWithProviders();
    expect(screen.getByText("UPSTOX · Upstox")).toBeInTheDocument();
  });
});
