/**
 * WelcomeCard.greeting.test.tsx — Explore `/home` greeting uses IST buckets.
 *
 * FT-HOME-001: at ~12:01 IST the card must say Good afternoon even when the
 * host clock is evening (or morning) in the browser's own zone.
 */

import { render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { fromIstParts } from "@/lib/ist";

vi.mock("@/hooks/usePositions", () => ({
  usePositions: () => ({ data: undefined, isLoading: false }),
}));
vi.mock("@/hooks/useAccountReadsEnabled", () => ({
  useAccountReadsEnabled: () => false,
}));
vi.mock("@/stores/tradingStore", () => ({
  useTradingStore: (sel: (s: { totalPnl: number }) => unknown) => sel({ totalPnl: 0 }),
}));
vi.mock("@/stores/settingsStore", () => ({
  useSettingsStore: (sel: (s: { name: string }) => unknown) => sel({ name: "Tester" }),
}));

import { useModeStore } from "@/stores/modeStore";
import { WelcomeCard } from "../WelcomeCard";

beforeEach(() => {
  useModeStore.setState({ mode: "explore" });
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
});

describe("WelcomeCard IST greeting", () => {
  it("shows Good afternoon at 12:01 IST", () => {
    vi.setSystemTime(fromIstParts(2026, 8, 10, 12, 1));
    render(<WelcomeCard />);
    expect(screen.getByRole("heading", { level: 2 })).toHaveTextContent(
      "Good afternoon, Tester",
    );
  });

  it("shows Good morning before noon IST", () => {
    vi.setSystemTime(fromIstParts(2026, 8, 10, 11, 59));
    render(<WelcomeCard />);
    expect(screen.getByRole("heading", { level: 2 })).toHaveTextContent(
      "Good morning, Tester",
    );
  });

  it("shows Good evening from 17:00 IST", () => {
    vi.setSystemTime(fromIstParts(2026, 8, 10, 17, 0));
    render(<WelcomeCard />);
    expect(screen.getByRole("heading", { level: 2 })).toHaveTextContent(
      "Good evening, Tester",
    );
  });
});
