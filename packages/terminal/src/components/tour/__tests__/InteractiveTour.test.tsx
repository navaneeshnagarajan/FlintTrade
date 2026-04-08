/**
 * InteractiveTour.test.tsx — Renders tour overlay with step dots and skip button.
 */

import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";

// ---------------------------------------------------------------------------
// Import (no store dependencies)
// ---------------------------------------------------------------------------

import InteractiveTour from "../InteractiveTour";

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("InteractiveTour", () => {
  it("renders the tour dialog with a Skip Tour button and step dots", () => {
    render(<InteractiveTour onComplete={vi.fn()} />);
    expect(screen.getByRole("dialog", { name: /interactive tour/i })).toBeInTheDocument();
    expect(screen.getByText("Skip Tour")).toBeInTheDocument();
    // 6 tour step dot buttons
    expect(screen.getAllByRole("button", { name: /tour step/i })).toHaveLength(6);
  });
});
