/**
 * AccountSwitcher.test.tsx — Renders account dropdown, shows connected accounts.
 */

import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

const mockAccounts = [
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

let storeState: { accounts: typeof mockAccounts; activeAccountId: string | null } = {
  accounts: mockAccounts,
  activeAccountId: "acc-1",
};

vi.mock("@/stores/brokerStore", () => ({
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

  it("returns null when there are no accounts", () => {
    storeState = { accounts: [], activeAccountId: null };
    const { container } = renderWithProviders();
    expect(container.innerHTML).toBe("");
  });
});
