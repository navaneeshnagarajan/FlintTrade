/**
 * SandboxControls.test.tsx — Renders the Practice capital and policy panel.
 *
 * Orders are placed through POST /api/v1/orders/place, not this panel.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const buildHeadersMock = vi.hoisted(() => vi.fn((includeJson: boolean) => ({
  ...(includeJson ? { "Content-Type": "application/json" } : {}),
  "X-API-Key": "test-key",
  Authorization: "Bearer practice-jwt",
})));

vi.mock("@/services/ftApi.helpers", () => ({
  buildHeaders: buildHeadersMock,
}));

import SandboxControls from "../SandboxControls";

// ---------------------------------------------------------------------------
// fetch stub — routes by URL suffix.
// ---------------------------------------------------------------------------

type JsonResp = { ok: boolean; json: () => Promise<unknown> };

function statusResp(): JsonResp {
  return {
    ok: true,
    json: async () => ({
      status: "success",
      data: { capital: 1_000_000, initial_capital: 1_000_000, pnl: 0, trades_count: 0 },
    }),
  };
}

function configResp(overrides: Record<string, unknown> = {}): JsonResp {
  return {
    ok: true,
    json: async () => ({
      status: "success",
      data: {
        config: {
          starting_capital: 1_000_000,
          equity_leverage: 1,
          futures_leverage: 1,
          option_buy_leverage: 1,
          option_sell_leverage: 1,
          squareoff_time: "15:15",
          mcx_squareoff_time: "23:25",
          ...overrides,
        },
      },
    }),
  };
}

const fetchMock = vi.fn(async (url: unknown, opts?: { body?: string }) => {
  const u = String(url);
  if (u.endsWith("/config")) {
    return configResp(opts?.body ? JSON.parse(opts.body) : {});
  }
  if (u.endsWith("/status")) return statusResp();
  return { ok: true, json: async () => ({ status: "success", data: {} }) };
});

beforeEach(() => {
  vi.stubGlobal("fetch", fetchMock);
  fetchMock.mockClear();
  buildHeadersMock.mockClear();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

function renderWithProviders() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <SandboxControls />
    </QueryClientProvider>,
  );
}

describe("SandboxControls", () => {
  it("renders the Virtual Capital and Practice policy sections", () => {
    renderWithProviders();
    expect(screen.getByText("Virtual Capital")).toBeInTheDocument();
    expect(screen.queryByText("Place Practice Order")).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/Place Practice Order/i)).not.toBeInTheDocument();
    expect(screen.getByText("Practice Policy")).toBeInTheDocument();
    expect(screen.getByText("Adjust Capital")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /export data/i })).toBeInTheDocument();
  });

  it("authenticates every direct sandbox request", async () => {
    renderWithProviders();

    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    for (const [, init] of fetchMock.mock.calls) {
      expect((init as RequestInit | undefined)?.headers).toEqual(
        expect.objectContaining({
          "X-API-Key": "test-key",
          Authorization: "Bearer practice-jwt",
        }),
      );
    }
  });

  it("does not post a sandbox order from this panel", async () => {
    renderWithProviders();
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    expect(fetchMock.mock.calls.some((call) => String(call[0]).endsWith("/order"))).toBe(false);
  });

  it("persists the complete Practice policy through the canonical config route", async () => {
    renderWithProviders();
    const equity = await screen.findByLabelText("Equity leverage");
    const save = screen.getByRole("button", { name: /save policy/i });
    await waitFor(() => expect(save).toBeEnabled());
    fireEvent.change(equity, { target: { value: "4" } });
    fireEvent.click(save);

    await waitFor(() => {
      const call = fetchMock.mock.calls.find((candidate) => (
        String(candidate[0]).endsWith("/config")
        && (candidate[1] as { method?: string } | undefined)?.method === "POST"
      ));
      expect(call).toBeTruthy();
      const body = JSON.parse((call![1] as { body: string }).body);
      expect(body).toEqual({
        starting_capital: 1_000_000,
        equity_leverage: 4,
        futures_leverage: 1,
        option_buy_leverage: 1,
        option_sell_leverage: 1,
        squareoff_time: "15:15",
        mcx_squareoff_time: "23:25",
      });
    });
  });

});
