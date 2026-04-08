/**
 * RouteErrorBoundary.test.tsx — Catches route errors, shows fallback.
 */

import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

vi.mock("@/components/brand/Logo", () => ({
  LogoIcon: ({ size }: { size: number }) => (
    <svg data-testid="logo-icon" width={size} height={size} />
  ),
}));

vi.mock("@/services/errorReporter", () => ({
  reportError: vi.fn().mockResolvedValue(undefined),
}));

// ---------------------------------------------------------------------------
// Import after mocks
// ---------------------------------------------------------------------------

import { RouteErrorBoundary } from "../RouteErrorBoundary";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function ThrowingComponent({ message }: { message: string }): React.ReactNode {
  throw new Error(message);
}

function GoodComponent() {
  return <div>Route content loaded</div>;
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("RouteErrorBoundary", () => {
  beforeEach(() => {
    vi.spyOn(console, "error").mockImplementation(() => undefined);
  });

  it("renders children when there is no error", () => {
    render(
      <RouteErrorBoundary routeName="Test">
        <GoodComponent />
      </RouteErrorBoundary>,
    );
    expect(screen.getByText("Route content loaded")).toBeInTheDocument();
  });

  it("shows error fallback with route name and Try Again button when child throws", () => {
    render(
      <RouteErrorBoundary routeName="Invest">
        <ThrowingComponent message="Something broke" />
      </RouteErrorBoundary>,
    );
    expect(screen.getByText("Invest encountered an error")).toBeInTheDocument();
    expect(screen.getByText("Something broke")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /try again/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /go home/i })).toBeInTheDocument();
  });
});
