/**
 * EtfTab.test.tsx — Example-mode chip and quote wording.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";

vi.mock("@/stores/themeStore", () => ({
  useThemeStore: Object.assign(
    (selector: (s: Record<string, unknown>) => unknown) =>
      selector({
        glass: { enabled: false, blur: 12, transparency: 20 },
        activeThemeId: "graphite",
        mode: "dark",
        customThemes: [],
        getActiveTheme: () => ({
          id: "graphite",
          name: "Graphite",
          dark: { colors: { card: "#16161f", border: "#2a2a3a", cardHover: "#1e1e2e" }, glass: { blur: 12, minOpacity: 0.8 } },
          light: { colors: { card: "#ffffff", border: "#e5e7eb", cardHover: "#f9fafb" }, glass: { blur: 12, minOpacity: 0.8 } },
        }),
        getResolvedMode: () => "dark",
      }),
    { getState: () => ({ glass: { enabled: false } }) },
  ),
}));

vi.mock("@/lib/cinematicThemes", () => ({
  getResolvedVariant: () => ({
    colors: { card: "#16161f", border: "#2a2a3a", cardHover: "#1e1e2e" },
    glass: { blur: 12, minOpacity: 0.8 },
  }),
}));

const quoteQuery = vi.hoisted(() => ({
  data: [] as Array<{ symbol: string; ltp: number; prev_close: number; volume: number }>,
  isLoading: false,
  isError: false,
  refetch: vi.fn(),
}));

vi.mock("@tanstack/react-query", () => ({
  useQuery: () => quoteQuery,
}));

vi.mock("@/services/api", () => ({
  getMultiQuotes: vi.fn().mockResolvedValue([]),
  normaliseMultiQuotes: (rows: unknown) => rows,
}));

import { useModeStore } from "@/stores/modeStore";
import { EtfTab } from "../EtfTab";

const LIVE_COPY = "live quotes via OpenAlgo. Refreshes every 30s";
const LOADED_QUOTES = [{ symbol: "NIFTYBEES", ltp: 2850, prev_close: 2800, volume: 10 }];

describe("EtfTab", () => {
  beforeEach(() => {
    quoteQuery.data = LOADED_QUOTES;
    quoteQuery.isLoading = false;
    quoteQuery.isError = false;
    useModeStore.setState({ mode: "explore" });
  });

  it("shows one Example chip and example prices when Explore quotes are loaded", () => {
    render(<EtfTab />);

    expect(screen.getAllByTestId("example-chip")).toHaveLength(1);
    expect(screen.getByText(/ETFs —/).textContent).toBe(
      "10 ETFs — Example prices. Connect a broker for live quotes.",
    );
    expect(screen.queryByText(new RegExp(LIVE_COPY))).not.toBeInTheDocument();
    expect(screen.getAllByText("₹2,850").length).toBeGreaterThan(0);
  });

  it("keeps live quote wording and no Example chip in Practice when quotes are loaded", () => {
    useModeStore.setState({ mode: "practice" });
    render(<EtfTab />);

    expect(screen.queryByTestId("example-chip")).not.toBeInTheDocument();
    expect(screen.getByText(/ETFs —/).textContent).toBe(
      "10 ETFs — live quotes via OpenAlgo. Refreshes every 30s.",
    );
  });

  it("keeps live quote wording in Live when quotes are loaded", () => {
    useModeStore.setState({ mode: "live" });
    render(<EtfTab />);

    expect(screen.queryByTestId("example-chip")).not.toBeInTheDocument();
    expect(screen.getByText(new RegExp(LIVE_COPY))).toBeInTheDocument();
  });
});
