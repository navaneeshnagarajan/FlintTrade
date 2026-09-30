/**
 * SocialTab.test.tsx — one Example chip for the strategy library view.
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

vi.mock("@/components/motion/StaggeredList", () => ({
  StaggeredList: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}));

vi.mock("@tanstack/react-query", () => ({
  useQuery: () => ({
    data: [],
    isLoading: false,
    isError: false,
    refetch: vi.fn(),
  }),
  useMutation: () => ({ mutate: vi.fn(), isPending: false }),
  useQueryClient: () => ({ invalidateQueries: vi.fn() }),
}));

import { useModeStore } from "@/stores/modeStore";
import { SocialTab } from "../SocialTab";

describe("SocialTab", () => {
  beforeEach(() => {
    useModeStore.setState({ mode: "explore" });
  });

  it("shows one Example chip after both sections fall back to example data", () => {
    render(<SocialTab />);

    expect(screen.getByText("Strategy Profiles")).toBeInTheDocument();
    expect(screen.getByText("Strategy Library")).toBeInTheDocument();
    expect(screen.getAllByTestId("example-chip")).toHaveLength(1);
  });

  it("hides the Example chip in Practice", () => {
    useModeStore.setState({ mode: "practice" });
    render(<SocialTab />);

    expect(screen.queryByTestId("example-chip")).not.toBeInTheDocument();
    expect(screen.getByText("Strategy Profiles")).toBeInTheDocument();
  });
});
