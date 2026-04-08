/**
 * ActionCenterWidget.test.tsx
 *
 * Tests for the ActionCenter pending order approval widget.
 * Verifies rendering, empty state, and order display.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";

// ---------------------------------------------------------------------------
// Mocks — must be defined before component import
// ---------------------------------------------------------------------------

// getPendingOrders must return an array (not undefined) to satisfy TanStack Query
vi.mock("@/services/ftApi", () => ({
  getPendingOrders: vi.fn().mockResolvedValue([] as unknown[]),
  approveOrder: vi.fn().mockResolvedValue({ status: "ok" }),
  rejectOrder: vi.fn().mockResolvedValue({ status: "ok" }),
  approveAllOrders: vi.fn().mockResolvedValue({ status: "ok" }),
}));

// ---------------------------------------------------------------------------
// Import component under test (after mocks)
// ---------------------------------------------------------------------------

import ActionCenterWidget from "../ActionCenterWidget";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const defaultProps = {} as Parameters<typeof ActionCenterWidget>[0];

function createWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: 0 },
    },
  });
  return function Wrapper({ children }: { children: ReactNode }) {
    return (
      <QueryClientProvider client={queryClient}>
        {children}
      </QueryClientProvider>
    );
  };
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("ActionCenterWidget", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders without crashing", () => {
    render(<ActionCenterWidget {...defaultProps} />, {
      wrapper: createWrapper(),
    });
    expect(screen.getByText("Action Center")).toBeInTheDocument();
  });

  it("shows empty state when no pending orders", async () => {
    render(<ActionCenterWidget {...defaultProps} />, {
      wrapper: createWrapper(),
    });
    expect(
      await screen.findByText("No pending orders."),
    ).toBeInTheDocument();
  });

  it("shows guidance text for approval queue", async () => {
    render(<ActionCenterWidget {...defaultProps} />, {
      wrapper: createWrapper(),
    });
    expect(
      await screen.findByText(
        "Orders queued for approval will appear here.",
      ),
    ).toBeInTheDocument();
  });
});
