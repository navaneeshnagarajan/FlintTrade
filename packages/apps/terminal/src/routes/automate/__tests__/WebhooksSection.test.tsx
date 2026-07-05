/**
 * WebhooksSection.test.tsx
 *
 * Tests for the Webhooks tab — verifies heading and sub-tabs.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import "@testing-library/jest-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React from "react";

// ---------------------------------------------------------------------------
// Mocks
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

vi.mock("@/components/ui/GlassCard", () => ({
  GlassCard: ({ children, ...props }: React.HTMLAttributes<HTMLDivElement>) => (
    <div {...props}>{children}</div>
  ),
  default: ({ children, ...props }: React.HTMLAttributes<HTMLDivElement>) => (
    <div {...props}>{children}</div>
  ),
}));

vi.mock("@/components/tradingview/AlertTemplateBrowser", () => ({
  AlertTemplateBrowser: () => <div data-testid="alert-template-browser" />,
}));

const mockGetWebhooks = vi.fn();
const mockCreateWebhook = vi.fn();
const mockDeleteWebhook = vi.fn();

vi.mock("@/services/ftApi", () => ({
  getWebhooks: (...args: unknown[]) => mockGetWebhooks(...args),
  createWebhook: (...args: unknown[]) => mockCreateWebhook(...args),
  deleteWebhook: (...args: unknown[]) => mockDeleteWebhook(...args),
}));

function createWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return ({ children }: { children: React.ReactNode }) =>
    React.createElement(QueryClientProvider, { client: queryClient }, children);
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

import WebhooksSection from "../WebhooksSection";

describe("WebhooksSection", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockGetWebhooks.mockResolvedValue({ webhooks: [] });
    mockCreateWebhook.mockResolvedValue({
      id: "v1/webhook/tradingview/nifty-trend-v1",
      path: "/v1/webhook/tradingview/nifty-trend-v1",
      name: "NIFTY Trend Signal",
      type: "tradingview",
      enabled: true,
    });
    mockDeleteWebhook.mockResolvedValue({ status: "success" });
  });

  it("renders without crashing and shows heading", () => {
    render(<WebhooksSection />, { wrapper: createWrapper() });
    expect(screen.getByText("Webhooks")).toBeInTheDocument();
  });

  it("displays the three sub-tabs: Active, Create, Alert Templates", () => {
    render(<WebhooksSection />, { wrapper: createWrapper() });
    // Use getAllByRole("tab") since Radix Tabs renders proper tab roles
    const tabs = screen.getAllByRole("tab");
    const tabLabels = tabs.map((t) => t.textContent);
    expect(tabLabels).toContain("Active");
    expect(tabLabels).toContain("Create");
    expect(tabLabels).toContain("Alert Templates");
  });

  it("loads registered webhooks from the backend registry", async () => {
    mockGetWebhooks.mockResolvedValueOnce({
      webhooks: [{
        id: "v1/webhook/tradingview/nifty-trend-v1",
        path: "/v1/webhook/tradingview/nifty-trend-v1",
        name: "NIFTY Trend Signal",
        type: "tradingview",
        enabled: true,
      }],
    });

    render(<WebhooksSection />, { wrapper: createWrapper() });

    expect(await screen.findByText("NIFTY Trend Signal")).toBeInTheDocument();
    expect(screen.getByText("/v1/webhook/tradingview/nifty-trend-v1")).toBeInTheDocument();
    expect(mockGetWebhooks).toHaveBeenCalled();
  });

  it("creates a mounted webhook endpoint through the backend service", async () => {
    const user = userEvent.setup();
    render(<WebhooksSection />, { wrapper: createWrapper() });

    const createTab = screen.getByRole("tab", { name: "Create" });
    await user.click(createTab);
    const nameInput = await screen.findByLabelText("Name");
    await user.type(nameInput, "NIFTY Trend Signal");
    await user.type(screen.getByLabelText("Strategy ID"), "nifty-trend-v1");
    await user.type(screen.getByLabelText(/Secret/i), "secret-1");
    await user.click(screen.getByRole("button", { name: /create endpoint/i }));

    await waitFor(() => expect(mockCreateWebhook).toHaveBeenCalledWith({
      name: "NIFTY Trend Signal",
      type: "tradingview",
      path: "/v1/webhook/tradingview/nifty-trend-v1",
      enabled: true,
      secret: "secret-1",
    }));
  });

  it("deletes registered webhooks through the backend service", async () => {
    mockGetWebhooks.mockResolvedValueOnce({
      webhooks: [{
        id: "v1/webhook/chartink/breakout",
        path: "/v1/webhook/chartink/breakout",
        name: "ChartInk Breakout",
        type: "chartink",
        enabled: true,
      }],
    });

    render(<WebhooksSection />, { wrapper: createWrapper() });

    expect(await screen.findByText("ChartInk Breakout")).toBeInTheDocument();
    fireEvent.click(screen.getByTitle("Delete endpoint"));

    await waitFor(() => expect(mockDeleteWebhook).toHaveBeenCalledWith("v1/webhook/chartink/breakout"));
  });
});
