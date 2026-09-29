/**
 * WelcomeCard.greeting.test.tsx — Explore `/home` greeting uses IST buckets.
 *
 * FT-HOME-001: at ~12:01 IST the card must say Good afternoon even when the
 * host clock is evening (or morning) in the browser's own zone.
 */

import { act, render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { fromIstParts } from "@/lib/ist";

const settingsState = vi.hoisted(() => ({ name: "Trader" }));

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
  useSettingsStore: (sel: (s: { name: string }) => unknown) => sel(settingsState),
}));

import { useAuthStore } from "@/stores/authStore";
import { useModeStore } from "@/stores/modeStore";
import { nextGreetingBinding } from "../operatorGreetingName";
import { WelcomeCard } from "../WelcomeCard";

beforeEach(() => {
  settingsState.name = "Trader";
  useModeStore.setState({ mode: "explore" });
  useAuthStore.setState({
    status: "logged-in",
    username: "Tester",
    token: "tok-tester",
    sessionGeneration: 1,
  });
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
  useAuthStore.getState().setLoggedOut();
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

  it("reads the signed-in operator and switches to the next sign-in", () => {
    vi.setSystemTime(fromIstParts(2026, 8, 10, 11, 59));
    settingsState.name = "Ada";
    useAuthStore.setState({
      status: "logged-in",
      username: "Ada",
      token: "tok-ada",
      sessionGeneration: 2,
    });
    render(<WelcomeCard />);
    expect(screen.getByRole("heading", { level: 2 })).toHaveTextContent("Good morning, Ada");

    settingsState.name = "Trader";
    act(() => {
      useAuthStore.getState().setLoggedIn("tok-bo", "Bo", "2099-01-01T02:30:00Z");
    });

    expect(screen.getByRole("heading", { level: 2 })).toHaveTextContent("Good morning, Bo");
    expect(screen.getByRole("heading", { level: 2 }).textContent).not.toMatch(/Trader/);
    expect(screen.getByRole("heading", { level: 2 }).textContent).not.toMatch(/Ada/);
  });

  it("uses the saved display name on mount and does not flash the username", () => {
    vi.setSystemTime(fromIstParts(2026, 8, 10, 11, 59));
    settingsState.name = "Meera";
    useAuthStore.setState({
      status: "logged-in",
      username: "Tester",
      token: "tok-tester",
      sessionGeneration: 4,
    });

    const first = nextGreetingBinding(null, {
      generation: 4,
      username: "Tester",
      settingsName: "Meera",
      loggedIn: true,
    });
    expect(first.name).toBe("Meera");

    render(<WelcomeCard />);
    const heading = screen.getByRole("heading", { level: 2 });
    expect(heading).toHaveTextContent("Good morning, Meera");
    expect(heading.textContent).not.toMatch(/Tester/);
  });

  it("falls back to the username when no display name is saved", () => {
    vi.setSystemTime(fromIstParts(2026, 8, 10, 11, 59));
    settingsState.name = "Trader";
    useAuthStore.setState({
      status: "logged-in",
      username: "Tester",
      token: "tok-tester",
      sessionGeneration: 5,
    });

    expect(nextGreetingBinding(null, {
      generation: 5,
      username: "Tester",
      settingsName: "Trader",
      loggedIn: true,
    }).name).toBe("Tester");
    expect(nextGreetingBinding(null, {
      generation: 5,
      username: "Tester",
      settingsName: "",
      loggedIn: true,
    }).name).toBe("Tester");

    render(<WelcomeCard />);
    expect(screen.getByRole("heading", { level: 2 })).toHaveTextContent(
      "Good morning, Tester",
    );
  });

  it("omits the name while the operator is unknown", () => {
    vi.setSystemTime(fromIstParts(2026, 8, 10, 11, 59));
    settingsState.name = "Trader";
    useAuthStore.setState({
      status: "logged-out",
      username: null,
      token: null,
      sessionGeneration: 3,
    });
    render(<WelcomeCard />);
    expect(screen.getByRole("heading", { level: 2 })).toHaveTextContent(/^Good morning$/);
    expect(screen.getByRole("heading", { level: 2 }).textContent).not.toMatch(/Trader/);
  });
});
