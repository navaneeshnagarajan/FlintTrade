/**
 * AISuggestionsPanel.test.tsx
 *
 * Tests for the AI Strategy Suggestions panel.
 * Verifies mood selector, strategy cards, persona-independent discovery, and deploy navigation.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { act, render, screen, fireEvent, within } from "@testing-library/react";
import "@testing-library/jest-dom";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

// Mock framer-motion
vi.mock("framer-motion", () => ({
  motion: {
    div: ({ children, ...props }: React.HTMLAttributes<HTMLDivElement>) => (
      <div {...props}>{children}</div>
    ),
    span: ({ children, ...props }: React.HTMLAttributes<HTMLSpanElement>) => (
      <span {...props}>{children}</span>
    ),
  },
  AnimatePresence: ({ children }: { children: React.ReactNode }) => (
    <>{children}</>
  ),
}));

// Mock react-router
const mockNavigate = vi.fn();
vi.mock("react-router", () => ({
  useNavigate: () => mockNavigate,
}));

import { useSettingsStore } from "@/stores/settingsStore";

// Mock motion config
vi.mock("@/lib/motion", () => ({
  motionConfig: {
    stagger: (i: number) => ({ delay: i * 0.05 }),
    prefersReducedMotion: () => false,
    transitions: { tab: { duration: 0.2 } },
    variants: {},
  },
  EASE_ENTER: [0.22, 1, 0.36, 1],
  DURATION: { slow: 0.3 },
}));

import AISuggestionsPanel from "../AISuggestionsPanel";

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("AISuggestionsPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useSettingsStore.setState({ persona: "trader", experience: "pro" });
  });

  it("renders the panel title", () => {
    render(<AISuggestionsPanel />);
    expect(screen.getByText("AI Strategy Suggestions")).toBeInTheDocument();
  });

  it("stays labelled illustrative — never sold as live alpha (FT-MONDAY-003)", () => {
    render(<AISuggestionsPanel />);
    const labels = screen.getAllByText("Illustrative");
    expect(labels.length).toBeGreaterThan(1);
    expect(
      screen.getByText(/illustrative local filter/i),
    ).toBeInTheDocument();
    expect(screen.queryByText(/live alpha/i)).toBeInTheDocument();
    expect(screen.getByText(/not actual backtest results/i)).toBeInTheDocument();
  });

  it("renders market mood selector with three options", () => {
    render(<AISuggestionsPanel />);
    expect(screen.getByText("Volatile")).toBeInTheDocument();
    expect(screen.getByText("Trending")).toBeInTheDocument();
    expect(screen.getByText("Sideways")).toBeInTheDocument();
  });

  it("renders the Market Mood heading", () => {
    render(<AISuggestionsPanel />);
    expect(screen.getByText("Market Mood")).toBeInTheDocument();
  });

  it("shows strategy cards on initial render (volatile mood)", () => {
    render(<AISuggestionsPanel />);
    // At least one "Deploy to Strategy Lab" button should be visible
    const deployButtons = screen.getAllByText("Deploy to Strategy Lab");
    expect(deployButtons.length).toBeGreaterThan(0);
    expect(deployButtons.length).toBeLessThanOrEqual(5);
  });

  it("mood chips expose aria-pressed from the same mood state", () => {
    render(<AISuggestionsPanel />);
    expect(screen.getByRole("button", { name: "Volatile" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "Trending" })).toHaveAttribute("aria-pressed", "false");
    expect(screen.getByRole("button", { name: "Sideways" })).toHaveAttribute("aria-pressed", "false");

    fireEvent.click(screen.getByRole("button", { name: "Sideways" }));

    expect(screen.getByRole("button", { name: "Volatile" })).toHaveAttribute("aria-pressed", "false");
    expect(screen.getByRole("button", { name: "Trending" })).toHaveAttribute("aria-pressed", "false");
    expect(screen.getByRole("button", { name: "Sideways" })).toHaveAttribute("aria-pressed", "true");
  });

  it("changing mood replaces recommendation cards and leaves no prior-mood card", () => {
    render(<AISuggestionsPanel />);
    fireEvent.click(screen.getByRole("button", { name: "Trending" }));
    expect(screen.getByText("Trend EMA Crossover")).toBeInTheDocument();
    expect(screen.queryByText("Iron Condor Strategy")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Sideways" }));

    expect(screen.getByText("Iron Condor Strategy")).toBeInTheDocument();
    expect(screen.queryByText("Trend EMA Crossover")).toBeNull();
    expect(screen.queryByText("ATR Breakout")).toBeNull();
    expect(screen.getByRole("button", { name: "Sideways" })).toHaveAttribute("aria-pressed", "true");
  });

  it("clears a previously selected strategy card when mood changes", () => {
    render(<AISuggestionsPanel />);
    fireEvent.click(screen.getByRole("button", { name: "Sideways" }));
    fireEvent.click(screen.getByRole("article", { name: "Iron Condor Strategy" }));
    expect(screen.getByRole("article", { name: "Iron Condor Strategy" })).toHaveAttribute(
      "aria-current",
      "true",
    );

    fireEvent.click(screen.getByRole("button", { name: "Trending" }));

    expect(screen.queryByRole("article", { name: "Iron Condor Strategy" })).toBeNull();
    expect(screen.queryByRole("article", { current: true })).toBeNull();
  });

  it("navigates to /lab with strategy key on Deploy click", () => {
    render(<AISuggestionsPanel />);
    const deployButtons = screen.getAllByText("Deploy to Strategy Lab");
    fireEvent.click(deployButtons[0]);
    expect(mockNavigate).toHaveBeenCalledTimes(1);
    expect(mockNavigate).toHaveBeenCalledWith(expect.stringContaining("/lab?strategy="));
  });

  it("deploys Trend EMA Crossover with its registry query key", () => {
    render(<AISuggestionsPanel />);
    fireEvent.click(screen.getByText("Trending"));
    const heading = screen.getByText("Trend EMA Crossover");
    const card = heading.closest("div.space-y-3") ?? heading.parentElement?.parentElement;
    expect(card).toBeTruthy();
    fireEvent.click(
      card!.querySelector("button") ??
        screen.getAllByText("Deploy to Strategy Lab").find((btn) => card!.contains(btn))!,
    );
    expect(mockNavigate).toHaveBeenCalledWith("/lab?strategy=TrendEMACrossover");
  });

  it("shows Win Rate, Return, and Max DD stats", () => {
    render(<AISuggestionsPanel />);
    // Check for stat labels
    const winRateLabels = screen.getAllByText("Win Rate");
    expect(winRateLabels.length).toBeGreaterThan(0);
    const returnLabels = screen.getAllByText("Return");
    expect(returnLabels.length).toBeGreaterThan(0);
    const maxDDLabels = screen.getAllByText("Max DD");
    expect(maxDDLabels.length).toBeGreaterThan(0);
  });

  it("disclaims inferred personal risk and requires independent execution checks", () => {
    render(<AISuggestionsPanel />);
    expect(screen.queryByText("Your risk profile:")).not.toBeInTheDocument();
    expect(screen.getByText("All risk categories are visible; none is a personal recommendation.")).toBeInTheDocument();
    expect(screen.getByText("Execution still requires independent risk checks")).toBeInTheDocument();
    expect(screen.getByText(/not an assumed personal risk profile/)).toBeInTheDocument();
  });

  it("keeps the same volatile strategies and risk labels when persona becomes beginner", () => {
    const view = render(<AISuggestionsPanel />);
    const before = screen.getAllByRole("article").map(card => card.getAttribute("aria-label"));
    act(() => { useSettingsStore.setState({ persona: "beginner", experience: "beginner" }); });
    view.rerender(<AISuggestionsPanel />);
    expect(screen.getAllByRole("article").map(card => card.getAttribute("aria-label"))).toEqual(before);
    expect(screen.getAllByText("high risk")).toHaveLength(3);
    expect(screen.getAllByText("medium risk")).toHaveLength(2);
    expect(screen.getByRole("article", { name: "ATR Breakout" })).toBeInTheDocument();
  });

  it("Next mood immediately refreshes chips and cards from the same mood state", () => {
    render(<AISuggestionsPanel />);
    // Still labelled Next mood — not a live "Refresh" fetch.
    expect(screen.queryByText("Refresh")).toBeNull();
    expect(screen.getByText("ATR Breakout")).toBeInTheDocument();

    fireEvent.click(screen.getByText("Next mood"));

    expect(screen.getByRole("button", { name: "Trending" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "Volatile" })).toHaveAttribute("aria-pressed", "false");
    expect(screen.getByText("Trend EMA Crossover")).toBeInTheDocument();
    expect(screen.queryByText("ATR Breakout")).toBeNull();
    expect(screen.queryByText("Iron Condor Strategy")).toBeNull();
  });

  // Persona-induced emptiness was explicitly retired. Every public mood has
  // real shipped entries; the internal empty fallback is not reachable here.
  it("keeps every shipped mood reachable and honestly labelled for a beginner", () => {
    useSettingsStore.setState({ persona: "beginner", experience: "beginner" });
    render(<AISuggestionsPanel />);
    for (const [mood, first] of [["Volatile", "ATR Breakout"], ["Trending", "Trend EMA Crossover"], ["Sideways", "Iron Condor Strategy"]]) {
      fireEvent.click(screen.getByRole("button", { name: mood }));
      expect(screen.getByRole("button", { name: mood })).toHaveAttribute("aria-pressed", "true");
      expect(screen.getAllByRole("article")).toHaveLength(5);
      expect(screen.getByRole("article", { name: first })).toBeInTheDocument();
      expect(screen.getAllByRole("button", { name: "Deploy to Strategy Lab" })).toHaveLength(5);
      expect(screen.queryByText("No strategies match this mood + risk combination.")).not.toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "Try another mood" })).not.toBeInTheDocument();
      expect(screen.getByText(/not a live AI fetch/)).toBeInTheDocument();
      expect(screen.getByText(/not actual backtest results/)).toBeInTheDocument();
      expect(screen.getByText(/none is a personal recommendation/)).toBeInTheDocument();
    }
    expect(mockNavigate).not.toHaveBeenCalled();
  });

  it("Next mood cycles all moods for a beginner, retires selection and retains exact deploy navigation", () => {
    useSettingsStore.setState({ persona: "beginner", experience: "beginner" });
    render(<AISuggestionsPanel />);
    fireEvent.click(screen.getByRole("article", { name: "ATR Breakout" }));
    expect(screen.getByRole("article", { name: "ATR Breakout" })).toHaveAttribute("aria-current", "true");
    fireEvent.click(screen.getByRole("button", { name: "Next mood" }));
    expect(screen.getByRole("button", { name: "Trending" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByText("Portfolio Momentum Rotation")).toBeInTheDocument();
    expect(screen.queryByRole("article", { current: true })).not.toBeInTheDocument();
    expect(screen.queryByText("ATR Breakout")).not.toBeInTheDocument();
    fireEvent.click(within(screen.getByRole("article", { name: "Portfolio Momentum Rotation" })).getByRole("button", { name: "Deploy to Strategy Lab" }));
    expect(mockNavigate).toHaveBeenCalledExactlyOnceWith("/lab?strategy=PortfolioMomentumRotation");
    fireEvent.click(screen.getByRole("button", { name: "Next mood" }));
    expect(screen.getByRole("button", { name: "Sideways" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("article", { name: "Iron Condor Strategy" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Next mood" }));
    expect(screen.getByRole("button", { name: "Volatile" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("article", { name: "ATR Breakout" })).toBeInTheDocument();
    expect(screen.queryByText("Iron Condor Strategy")).not.toBeInTheDocument();
    expect(screen.queryByRole("article", { current: true })).not.toBeInTheDocument();
    expect(screen.getByText(/not actual backtest results/)).toBeInTheDocument();
  });

});
