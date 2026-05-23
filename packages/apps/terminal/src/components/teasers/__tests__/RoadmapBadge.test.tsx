/**
 * RoadmapBadge.test.tsx
 *
 * Tests for the RoadmapBadge 4-stage progress indicator.
 * Verifies dot count, active stage highlighting, completed stage styling,
 * and snapshot stability.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";
import { RoadmapBadge } from "../RoadmapBadge";
import { ROADMAP_STAGE_LABELS } from "../types";

// ---------------------------------------------------------------------------
// Mock framer-motion — avoids JSDOM layout animation issues
// ---------------------------------------------------------------------------
vi.mock("framer-motion", () => ({
  motion: {
    div: ({ children, ...props }: React.HTMLAttributes<HTMLDivElement>) => (
      <div {...props}>{children}</div>
    ),
  },
  AnimatePresence: ({ children }: { children: React.ReactNode }) => (
    <>{children}</>
  ),
}));

// ---------------------------------------------------------------------------
// Silence matchMedia
// ---------------------------------------------------------------------------
beforeEach(() => {
  Object.defineProperty(window, "matchMedia", {
    writable: true,
    value: vi.fn().mockImplementation(() => ({
      matches: false,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    })),
  });
});

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("RoadmapBadge", () => {
  it("renders 4 stage dots", () => {
    render(<RoadmapBadge status="preview" />);

    // Each dot has role="img" with aria-label containing the stage label
    const dots = screen.getAllByRole("img");
    expect(dots).toHaveLength(4);
  });

  it("highlights correct dot for in_dev status — 2nd dot is active", () => {
    render(<RoadmapBadge status="in_dev" />);

    // The active dot has aria-label "In Dev: current"
    const activeDot = screen.getByRole("img", {
      name: `${ROADMAP_STAGE_LABELS.in_dev}: current`,
    });
    expect(activeDot).toBeInTheDocument();

    // Preceding stage (preview/Designed) should be "completed"
    const completedDot = screen.getByRole("img", {
      name: `${ROADMAP_STAGE_LABELS.preview}: completed`,
    });
    expect(completedDot).toBeInTheDocument();
  });

  it("shows completed style for stages before the active stage", () => {
    // For status "testing" (index 2), stages 0 (preview) and 1 (in_dev) are completed
    render(<RoadmapBadge status="testing" />);

    const completedDesigned = screen.getByRole("img", {
      name: `${ROADMAP_STAGE_LABELS.preview}: completed`,
    });
    const completedInDev = screen.getByRole("img", {
      name: `${ROADMAP_STAGE_LABELS.in_dev}: completed`,
    });

    expect(completedDesigned).toBeInTheDocument();
    expect(completedInDev).toBeInTheDocument();

    // Completed dots carry the bg-blue-400 class
    expect(completedDesigned.className).toContain("bg-blue-400");
    expect(completedInDev.className).toContain("bg-blue-400");
  });

  it("matches snapshot for testing status", () => {
    const { container } = render(<RoadmapBadge status="testing" />);
    expect(container).toMatchSnapshot();
  });
});
