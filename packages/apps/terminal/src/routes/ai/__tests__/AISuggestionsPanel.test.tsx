/**
 * AISuggestionsPanel.test.tsx
 *
 * Tests for the AI Strategy Suggestions panel.
 * Verifies mood selector, strategy cards, risk filtering, and deploy navigation.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
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

// Mock settingsStore — default: trader + pro experience = high risk
let mockPersona = "trader";
let mockExperience = "pro";
vi.mock("@/stores/settingsStore", () => ({
  useSettingsStore: (selector: (state: Record<string, string>) => string) =>
    selector({ persona: mockPersona, experience: mockExperience }),
}));

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
    mockPersona = "trader";
    mockExperience = "pro";
  });

  it("renders the panel title", () => {
    render(<AISuggestionsPanel />);
    expect(screen.getByText("AI Strategy Suggestions")).toBeInTheDocument();
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

  it("shows risk profile badge", () => {
    render(<AISuggestionsPanel />);
    expect(screen.getByText("Your risk profile:")).toBeInTheDocument();
  });

  it("filters strategies by risk for beginner persona", () => {
    mockPersona = "beginner";
    mockExperience = "beginner";
    render(<AISuggestionsPanel />);
    // Beginner = low risk: should only show low-risk strategies
    const highRiskBadges = screen.queryAllByText("high risk");
    expect(highRiskBadges.length).toBe(0);
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

  it("shows an honest empty state with Try another mood when mood and risk match nothing", () => {
    mockPersona = "beginner";
    mockExperience = "beginner";
    render(<AISuggestionsPanel />);

    expect(
      screen.getByText("No strategies match this mood + risk combination."),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Try another mood" })).toBeInTheDocument();
    expect(screen.queryByText("ATR Breakout")).toBeNull();
    expect(screen.queryByText("Iron Condor Strategy")).toBeNull();
    expect(screen.queryByText("Deploy to Strategy Lab")).toBeNull();
  });

  it("Try another mood advances the filter and replaces the empty state", () => {
    mockPersona = "beginner";
    mockExperience = "beginner";
    render(<AISuggestionsPanel />);

    fireEvent.click(screen.getByRole("button", { name: "Try another mood" }));

    expect(screen.getByRole("button", { name: "Trending" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByText("Portfolio Momentum Rotation")).toBeInTheDocument();
    expect(screen.queryByText("No strategies match this mood + risk combination.")).toBeNull();
    expect(screen.queryByText("ATR Breakout")).toBeNull();
  });
});
