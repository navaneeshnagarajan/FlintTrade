/**
 * ErrorBoundary.test.tsx — Tests that the error boundary catches errors
 * and displays the fallback recovery UI.
 */

import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";

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

import { ErrorBoundary } from "../ErrorBoundary";

// ---------------------------------------------------------------------------
// Helper: a component that throws on render
// ---------------------------------------------------------------------------

function ThrowingComponent({ message }: { message: string }): React.ReactNode {
  throw new Error(message);
}

function GoodComponent() {
  return <div>All clear</div>;
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("ErrorBoundary", () => {
  beforeEach(() => {
    // Suppress console.error from React and ErrorBoundary during intentional throws
    vi.spyOn(console, "error").mockImplementation(() => undefined);
  });

  it("renders children when there is no error", () => {
    render(
      <ErrorBoundary>
        <GoodComponent />
      </ErrorBoundary>,
    );
    expect(screen.getByText("All clear")).toBeInTheDocument();
  });

  it("catches errors and shows fallback UI with error message", () => {
    render(
      <ErrorBoundary>
        <ThrowingComponent message="Test crash" />
      </ErrorBoundary>,
    );

    expect(screen.getByText("Something went wrong")).toBeInTheDocument();
    expect(screen.getByText("Test crash")).toBeInTheDocument();
    expect(screen.getByText("Reload")).toBeInTheDocument();
    expect(screen.getByText("Go Home")).toBeInTheDocument();
  });
});
