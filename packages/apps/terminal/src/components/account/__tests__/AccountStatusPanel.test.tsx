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

// NOTE: `get()` UNWRAPS the backend's `{status, data: {...}}` envelope
// (parseResponse returns `json.data`), so it resolves to the inner
// `{accounts, summary}` — NOT a doubly-wrapped `{data: {...}}`. These mocks must
// mirror that real contract; an earlier version wrapped them in an extra `data`
// key, which matched a double-unwrap bug in the component and hid it.

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
      accounts: [
        { account_id: "A1", name: "Primary", enabled: true, connected: true, authenticated: true, needs_reauth: false, latency_ms: 12, error: "" },
        { account_id: "A2", name: "Secondary", enabled: true, connected: true, authenticated: false, needs_reauth: true, latency_ms: 20, error: "HTTP 403" },
      ],
      summary: { total: 2, connected: 2, authenticated: 1, needs_reauth: 1 },
    });
    renderPanel();
    expect(await screen.findByText("Primary")).toBeInTheDocument();
    expect(screen.getByText("Secondary")).toBeInTheDocument();
    expect(screen.getByText(/1 need re-auth/i)).toBeInTheDocument();
    expect(screen.getByText("HTTP 403")).toBeInTheDocument();
  });

  it("makes the Re-auth badge an actionable link to the unified broker settings", async () => {
    mockGet.mockResolvedValue({
      accounts: [
        { account_id: "A2", name: "Secondary", enabled: true, connected: true, authenticated: false, needs_reauth: true, latency_ms: 20, error: "HTTP 403" },
      ],
      summary: { total: 1, connected: 1, authenticated: 0, needs_reauth: 1 },
    });
    renderPanel();

    // The needs-reauth account must DRIVE the operator to act, not just report.
    const link = await screen.findByRole("link", { name: /re-authenticate secondary/i });
    expect(link).toHaveAttribute("href", "/settings#brokers");
  });

  it("deep-links native broker reauth to the broker settings section", async () => {
    mockGet.mockResolvedValue({
      accounts: [
        {
          account_id: "UPX1",
          source: "native",
          broker: "upstox",
          broker_display: "Upstox",
          name: "Upstox main",
          enabled: true,
          connected: false,
          authenticated: false,
          needs_reauth: true,
          latency_ms: 0,
          error: "Needs fresh native broker login.",
        },
      ],
      summary: { total: 1, connected: 0, authenticated: 0, needs_reauth: 1 },
    });
    renderPanel();

    expect(await screen.findByText("Upstox main")).toBeInTheDocument();
    expect(screen.getByText(/Upstox · Native/i)).toBeInTheDocument();
    const link = screen.getByRole("link", { name: /re-authenticate upstox main/i });
    expect(link).toHaveAttribute("href", "/settings#brokers");
  });

  it("shows retryable native broker login outages without a reauth link", async () => {
    mockGet.mockResolvedValue({
      accounts: [
        {
          account_id: "UPX1",
          source: "native",
          broker: "upstox",
          broker_display: "Upstox",
          name: "Upstox retry",
          enabled: true,
          connected: false,
          authenticated: false,
          needs_reauth: false,
          login_retryable: true,
          latency_ms: 0,
          error: "Broker login is temporarily unavailable; retry later.",
        },
      ],
      summary: { total: 1, connected: 0, authenticated: 0, needs_reauth: 0 },
    });
    renderPanel();

    expect(await screen.findByText("Upstox retry")).toBeInTheDocument();
    expect(screen.getByText("Retry later")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /re-authenticate upstox retry/i })).not.toBeInTheDocument();
    expect(screen.queryByText(/need re-auth/i)).not.toBeInTheDocument();
  });

  it("shows an empty state when no accounts are connected", async () => {
    mockGet.mockResolvedValue({ accounts: [], summary: { total: 0, connected: 0, authenticated: 0, needs_reauth: 0 } });
    renderPanel();
    expect(await screen.findByText(/no broker accounts connected/i)).toBeInTheDocument();
  });

  it("shows an unavailable message on error", async () => {
    mockGet.mockRejectedValue(new Error("boom"));
    renderPanel();
    expect(await screen.findByText(/unavailable right now/i)).toBeInTheDocument();
  });
});
