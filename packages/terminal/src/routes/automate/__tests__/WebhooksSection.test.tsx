/**
 * WebhooksSection.test.tsx
 *
 * Tests for the Webhooks tab — verifies heading and sub-tabs.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";

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

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

import WebhooksSection from "../WebhooksSection";

describe("WebhooksSection", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("renders without crashing and shows heading", () => {
    render(<WebhooksSection />);
    expect(screen.getByText("Webhooks")).toBeInTheDocument();
  });

  it("displays the three sub-tabs: Active, Create, Alert Templates", () => {
    render(<WebhooksSection />);
    // Use getAllByRole("tab") since Radix Tabs renders proper tab roles
    const tabs = screen.getAllByRole("tab");
    const tabLabels = tabs.map((t) => t.textContent);
    expect(tabLabels).toContain("Active");
    expect(tabLabels).toContain("Create");
    expect(tabLabels).toContain("Alert Templates");
  });
});
