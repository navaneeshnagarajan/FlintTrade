/**
 * ActionCenterWidget.test.tsx
 *
 * Tests for the ActionCenter pending order approval widget.
 * Verifies rendering, empty state, and order display.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { makeDockviewPanelProps } from "@/test-utils/dockviewPanelProps";

// ---------------------------------------------------------------------------
// Mocks — must be defined before component import
// ---------------------------------------------------------------------------

// getPendingOrders must return an array (not undefined) to satisfy TanStack Query
vi.mock("@/services/ftApi", () => ({
  getPendingOrders: vi.fn().mockResolvedValue([] as unknown[]),
  approveOrder: vi.fn().mockResolvedValue({ status: "ok" }),
  rejectOrder: vi.fn().mockResolvedValue({ status: "ok" }),
}));

// ---------------------------------------------------------------------------
// Import component under test (after mocks)
// ---------------------------------------------------------------------------

import {
  getPendingOrders,
  approveOrder,
  rejectOrder,
  type PendingOrder,
} from "@/services/ftApi";
import ActionCenterWidget from "../ActionCenterWidget";

const mockGetPendingOrders = vi.mocked(getPendingOrders);
const mockApproveOrder = vi.mocked(approveOrder);
const mockRejectOrder = vi.mocked(rejectOrder);

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const defaultProps = makeDockviewPanelProps();

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

  // ── Mutation error honesty — a failed approval must never snap back silently ──

  describe("approve/reject failures", () => {
    const ORDER: PendingOrder = {
      id: "po-1",
      symbol: "NIFTY24APR24000CE",
      exchange: "NFO",
      action: "BUY",
      quantity: 75,
      price: 0,
      order_type: "MARKET",
      product: "NRML",
      strategy: "Theta",
      created_at: new Date().toISOString(),
      reason: "L2 position limit",
    };

    beforeEach(() => {
      mockGetPendingOrders.mockResolvedValue([ORDER]);
    });

    it("requires pending live intents to be reviewed one at a time", async () => {
      render(<ActionCenterWidget {...defaultProps} />, { wrapper: createWrapper() });

      await screen.findByRole("button", { name: "Approve order: BUY 75 NIFTY24APR24000CE" });
      expect(screen.queryByRole("button", { name: /approve all/i })).not.toBeInTheDocument();
    });

    it("surfaces the server message with a retry affordance when approval fails", async () => {
      mockApproveOrder.mockRejectedValue(new Error("Kill switch active — approvals disabled"));
      render(<ActionCenterWidget {...defaultProps} />, { wrapper: createWrapper() });

      fireEvent.click(
        await screen.findByRole("button", { name: "Approve order: BUY 75 NIFTY24APR24000CE" }),
      );

      const alert = await screen.findByRole("alert");
      expect(alert).toHaveTextContent(/approval failed/i);
      expect(alert).toHaveTextContent("Kill switch active — approvals disabled");
      expect(screen.getByRole("button", { name: "Retry failed action" })).toBeInTheDocument();
    });

    it("retries the same approval when Retry is clicked", async () => {
      mockApproveOrder.mockRejectedValue(new Error("backend offline"));
      render(<ActionCenterWidget {...defaultProps} />, { wrapper: createWrapper() });

      fireEvent.click(
        await screen.findByRole("button", { name: "Approve order: BUY 75 NIFTY24APR24000CE" }),
      );
      await screen.findByRole("alert");
      expect(mockApproveOrder).toHaveBeenCalledTimes(1);

      fireEvent.click(screen.getByRole("button", { name: "Retry failed action" }));
      await waitFor(() => expect(mockApproveOrder).toHaveBeenCalledTimes(2));
      expect(mockApproveOrder).toHaveBeenLastCalledWith("po-1");
    });

    it("surfaces a rejection failure and clears it on dismiss", async () => {
      mockRejectOrder.mockRejectedValue(new Error("order already executed"));
      render(<ActionCenterWidget {...defaultProps} />, { wrapper: createWrapper() });

      fireEvent.click(
        await screen.findByRole("button", { name: "Reject order: BUY 75 NIFTY24APR24000CE" }),
      );

      const alert = await screen.findByRole("alert");
      expect(alert).toHaveTextContent(/rejection failed/i);
      expect(alert).toHaveTextContent("order already executed");

      fireEvent.click(screen.getByRole("button", { name: "Dismiss error" }));
      expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    });

    it("clears the failure banner when a subsequent action starts", async () => {
      mockApproveOrder.mockRejectedValueOnce(new Error("transient failure")).mockResolvedValue({ status: "ok" });
      render(<ActionCenterWidget {...defaultProps} />, { wrapper: createWrapper() });

      fireEvent.click(
        await screen.findByRole("button", { name: "Approve order: BUY 75 NIFTY24APR24000CE" }),
      );
      await screen.findByRole("alert");

      fireEvent.click(screen.getByRole("button", { name: "Retry failed action" }));
      await waitFor(() => expect(screen.queryByRole("alert")).not.toBeInTheDocument());
    });
  });
});
