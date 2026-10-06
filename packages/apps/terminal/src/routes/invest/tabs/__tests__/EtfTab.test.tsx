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

const LIVE_COPY = "live quotes via your native broker. Refreshes every 30s";
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
      "10 ETFs — live quotes via your native broker. Refreshes every 30s.",
    );
  });

  it.each(["practice", "live"] as const)("labels fallback prices in %s even outside Example mode", (mode) => {
    useModeStore.setState({ mode });
    quoteQuery.data = [];
    render(<EtfTab />);
    expect(screen.getByTestId("example-chip")).toHaveTextContent("Example");
    expect(screen.getByText(/ETFs — sample prices/)).toBeInTheDocument();
    expect(screen.queryByText(new RegExp(LIVE_COPY))).not.toBeInTheDocument();
  });

  it("keeps live quote wording in Live when quotes are loaded", () => {
    useModeStore.setState({ mode: "live" });
    render(<EtfTab />);

    expect(screen.queryByTestId("example-chip")).not.toBeInTheDocument();
    expect(screen.getByText(new RegExp(LIVE_COPY))).toBeInTheDocument();
  });

  it.each(["practice", "live", "explore"] as const)("identifies pending %s quotes without claiming live figures", (mode) => {
    useModeStore.setState({ mode });
    quoteQuery.data = [];
    quoteQuery.isLoading = true;
    render(<EtfTab />);
    expect(screen.getByRole("status", { name: "Loading ETF quotes" })).toBeInTheDocument();
    expect(screen.getByText(mode === "explore"
      ? /fetching Example quotes/
      : /fetching native quotes/)).toBeInTheDocument();
    expect(screen.queryByText(/live quotes/i)).not.toBeInTheDocument();
    expect(screen.queryByText("₹2,850")).not.toBeInTheDocument();
    expect(screen.queryByText("₹265")).not.toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("uses disclosed example rows when a refetch fails with native data still cached", () => {
    useModeStore.setState({ mode: "practice" });
    const view = render(<EtfTab />);
    expect(screen.getAllByText("₹2,850").length).toBeGreaterThan(0);
    quoteQuery.isError = true;
    view.rerender(<EtfTab />);
    expect(screen.queryByText("₹2,850")).not.toBeInTheDocument();
    expect(screen.getAllByText("₹265").length).toBeGreaterThan(0);
    expect(screen.getByTestId("example-chip")).toBeInTheDocument();
    expect(screen.getByText(/Example prices illustrate this ETF universe/)).toBeInTheDocument();
  });
});
