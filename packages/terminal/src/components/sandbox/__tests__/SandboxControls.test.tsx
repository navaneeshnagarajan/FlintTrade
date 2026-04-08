/**
 * SandboxControls.test.tsx — Renders sandbox settings panel.
 */

import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

// ---------------------------------------------------------------------------
// Import after setup (no store mocks needed — uses TanStack Query directly)
// ---------------------------------------------------------------------------

import SandboxControls from "../SandboxControls";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function renderWithProviders() {
  const qc = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
  return render(
    <QueryClientProvider client={qc}>
      <SandboxControls />
    </QueryClientProvider>,
  );
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("SandboxControls", () => {
  it("renders the Virtual Capital section", () => {
    renderWithProviders();
    expect(screen.getByText("Virtual Capital")).toBeInTheDocument();
  });

  it("renders the Adjust Capital form and Data Management buttons", () => {
    renderWithProviders();
    expect(screen.getByText("Adjust Capital")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /export data/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /import data/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /reset all data/i })).toBeInTheDocument();
  });
});
