/**
 * AccountStatusPanel.test — the Account Manager connection + reauth surface.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { AccountStatusPanel } from "../AccountStatusPanel";

vi.mock("@/services/ftApi", () => ({ get: vi.fn() }));
import { get } from "@/services/ftApi";

const mockGet = get as unknown as ReturnType<typeof vi.fn>;

function renderPanel() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <AccountStatusPanel />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("AccountStatusPanel", () => {
  beforeEach(() => vi.clearAllMocks());

  it("renders per-account connection + reauth state", async () => {
    mockGet.mockResolvedValue({
      data: {
        accounts: [
          { account_id: "A1", name: "Primary", enabled: true, connected: true, authenticated: true, needs_reauth: false, latency_ms: 12, error: "" },
          { account_id: "A2", name: "Secondary", enabled: true, connected: true, authenticated: false, needs_reauth: true, latency_ms: 20, error: "HTTP 403" },
        ],
        summary: { total: 2, connected: 2, authenticated: 1, needs_reauth: 1 },
      },
    });
    renderPanel();
    expect(await screen.findByText("Primary")).toBeInTheDocument();
    expect(screen.getByText("Secondary")).toBeInTheDocument();
    expect(screen.getByText(/1 need re-auth/i)).toBeInTheDocument();
    expect(screen.getByText("HTTP 403")).toBeInTheDocument();
  });

  it("makes the Re-auth badge an actionable link to the Broker Gateway settings", async () => {
    mockGet.mockResolvedValue({
      data: {
        accounts: [
          { account_id: "A2", name: "Secondary", enabled: true, connected: true, authenticated: false, needs_reauth: true, latency_ms: 20, error: "HTTP 403" },
        ],
        summary: { total: 1, connected: 1, authenticated: 0, needs_reauth: 1 },
      },
    });
    renderPanel();

    // The needs-reauth account must DRIVE the operator to act, not just report.
    const link = await screen.findByRole("link", { name: /re-authenticate secondary/i });
    expect(link).toHaveAttribute("href", "/settings#api");
  });

  it("shows an empty state when no accounts are connected", async () => {
    mockGet.mockResolvedValue({ data: { accounts: [], summary: { total: 0, connected: 0, authenticated: 0, needs_reauth: 0 } } });
    renderPanel();
    expect(await screen.findByText(/no broker accounts connected/i)).toBeInTheDocument();
  });

  it("shows an unavailable message on error", async () => {
    mockGet.mockRejectedValue(new Error("boom"));
    renderPanel();
    expect(await screen.findByText(/unavailable right now/i)).toBeInTheDocument();
  });
});
