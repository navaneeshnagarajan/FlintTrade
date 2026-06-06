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

// Mock react-router-dom
const mockNavigate = vi.fn();
vi.mock("react-router-dom", () => ({
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

  it("clicking a mood button changes displayed strategies", () => {
    render(<AISuggestionsPanel />);
    // Click "Trending" mood
    fireEvent.click(screen.getByText("Trending"));
    // Should still have deploy buttons (trending strategies exist)
    const deployButtons = screen.getAllByText("Deploy to Strategy Lab");
    expect(deployButtons.length).toBeGreaterThan(0);
  });

  it("navigates to /lab with strategy key on Deploy click", () => {
    render(<AISuggestionsPanel />);
    const deployButtons = screen.getAllByText("Deploy to Strategy Lab");
    fireEvent.click(deployButtons[0]);
    expect(mockNavigate).toHaveBeenCalledTimes(1);
    expect(mockNavigate).toHaveBeenCalledWith(expect.stringContaining("/lab?strategy="));
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

  it("the 'Next mood' control cycles the market-mood scenario (honestly labelled — not a data refresh)", () => {
    render(<AISuggestionsPanel />);
    // The control must NOT masquerade as a live "Refresh" — there is no AI
    // suggestion backend; it only cycles the illustrative mood scenario.
    expect(screen.queryByText("Refresh")).toBeNull();
    const nextMood = screen.getByText("Next mood");
    fireEvent.click(nextMood);
    const deployButtons = screen.getAllByText("Deploy to Strategy Lab");
    expect(deployButtons.length).toBeGreaterThan(0);
  });
});
