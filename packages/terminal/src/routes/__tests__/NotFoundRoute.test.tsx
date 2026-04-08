/**
 * NotFoundRoute.test.tsx
 *
 * Tests for the 404 catch-all page.
 * Verifies the 404 message and navigation actions.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import "@testing-library/jest-dom";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

const mockNavigate = vi.fn();

vi.mock("react-router-dom", () => ({
  useNavigate: () => mockNavigate,
}));

vi.mock("@/components/brand/Logo", () => ({
  LogoIcon: () => <svg data-testid="logo-icon" />,
}));

// ---------------------------------------------------------------------------
// Import after mocks
// ---------------------------------------------------------------------------

import NotFoundRoute from "../NotFoundRoute";

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("NotFoundRoute", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders the 404 message and heading", () => {
    render(<NotFoundRoute />);

    expect(screen.getByText("404")).toBeInTheDocument();
    expect(screen.getByText("Page not found")).toBeInTheDocument();
    expect(screen.getByRole("main", { name: /page not found/i })).toBeInTheDocument();
  });

  it("navigates home when Go Home button is clicked", async () => {
    const user = userEvent.setup();
    render(<NotFoundRoute />);

    await user.click(screen.getByRole("button", { name: /go home/i }));

    expect(mockNavigate).toHaveBeenCalledWith("/");
  });
});
