import { render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/hooks/usePositions", () => ({
  usePositions: () => ({ data: undefined, isLoading: false }),
}));
vi.mock("@/hooks/useAccountReadsEnabled", () => ({
  useAccountReadsEnabled: () => true,
}));
vi.mock("@/stores/tradingStore", () => ({
  useCurrentTradingState: () => ({ totalPnl: -803, positionsStatus: "ready" }),
  useTradingStore: (sel: (s: { totalPnl: number }) => unknown) => sel({ totalPnl: -803 }),
}));
vi.mock("@/stores/settingsStore", () => ({
  useSettingsStore: (sel: (s: { name: string }) => unknown) => sel({ name: "Trader" }),
}));

import { useAuthStore } from "@/stores/authStore";
import { useModeStore } from "@/stores/modeStore";
import { WelcomeCard } from "../WelcomeCard";

beforeEach(() => {
  useModeStore.setState({ mode: "practice" });
  useAuthStore.setState({
    status: "logged-in",
    username: "Tester",
    token: "tok-tester",
    sessionGeneration: 1,
  });
});

afterEach(() => {
  useAuthStore.getState().setLoggedOut();
});

describe("WelcomeCard P&L", () => {
  it("keeps a negative P&L sign on the same line as the amount", () => {
    render(<WelcomeCard />);
    const value = screen.getByText("Today's P&L").parentElement?.querySelector("p.font-mono");
    expect(value).toBeTruthy();
    expect(value).toHaveClass("whitespace-nowrap");
    expect(value).toHaveTextContent(/₹/);
    expect(value).toHaveTextContent(/803/);
    expect(value).toHaveTextContent(/-/);
  });
});
