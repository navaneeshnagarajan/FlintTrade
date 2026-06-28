import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";

// Mock framer-motion to avoid animation issues in tests
vi.mock("framer-motion", () => ({
  AnimatePresence: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  motion: {
    div: ({ children, ...props }: Record<string, unknown>) => (
      <div {...props}>{children as React.ReactNode}</div>
    ),
    span: ({ children, ...props }: Record<string, unknown>) => (
      <span {...props}>{children as React.ReactNode}</span>
    ),
  },
}));

vi.mock("@/lib/motion", () => ({
  motionConfig: {
    prefersReducedMotion: () => true,
    duration: { fast: 0, normal: 0, slow: 0 },
    ease: { enter: [0, 0, 1, 1] },
    transitions: { scale: { duration: 0 }, tab: { duration: 0 } },
  },
}));

// Mock hooks that depend on stores
vi.mock("@/hooks/useSkillLevel", () => ({
  useSkillLevel: () => "advanced",
}));

vi.mock("@/stores/skillStore", () => ({
  useSkillStore: Object.assign(() => ({}), {
    getState: () => ({ trackAction: vi.fn() }),
  }),
}));

vi.mock("@/components/help/SpotlightTour", () => ({
  SpotlightTour: () => null,
}));

vi.mock("@/lib/tourDefinitions", () => ({
  TOUR_DEFINITIONS: {},
}));

import LearnRoute from "../LearnRoute";

describe("LearnRoute", () => {
  it("renders the Learning Center heading", () => {
    render(<LearnRoute />);
    expect(screen.getByText("Learning Center")).toBeInTheDocument();
  });

  it("has sidebar sections for all tabs at advanced level", () => {
    render(<LearnRoute />);
    expect(screen.getByText("Market Basics")).toBeInTheDocument();
    expect(screen.getByText("Glossary")).toBeInTheDocument();
    expect(screen.getByText("Strategy Library")).toBeInTheDocument();
    expect(screen.getByText("Paper Trading")).toBeInTheDocument();
    expect(screen.getByText("Resource Hub")).toBeInTheDocument();
  });

  it("shows Market Basics content by default", () => {
    render(<LearnRoute />);
    // Market Basics tab content includes the first section title
    expect(screen.getByText("What are Stocks?")).toBeInTheDocument();
  });
});
