/**
 * SandboxControls.test.tsx — Renders sandbox settings panel + paper-order flow.
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
// fetch stub — routes by URL suffix. Tests override the /order handler.
// ---------------------------------------------------------------------------

type JsonResp = { ok: boolean; json: () => Promise<unknown> };
let orderResponder: (body: unknown) => JsonResp;

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
  if (u.endsWith("/order")) {
    return orderResponder(opts?.body ? JSON.parse(opts.body) : {});
  }
  if (u.endsWith("/config")) {
    return configResp(opts?.body ? JSON.parse(opts.body) : {});
  }
  if (u.endsWith("/status")) return statusResp();
  return { ok: true, json: async () => ({ status: "success", data: {} }) };
});

beforeEach(() => {
  orderResponder = () => ({
    ok: true,
    json: async () => ({
      status: "success",
      data: { order: { order_id: "OID1", status: "COMPLETE", message: "Filled 50 @ 100" } },
    }),
  });
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

async function fillOrder() {
  fireEvent.change(screen.getByLabelText("Order symbol"), { target: { value: "nifty" } });
  fireEvent.change(screen.getByLabelText("Order quantity"), { target: { value: "50" } });
  fireEvent.change(screen.getByLabelText("Order price"), { target: { value: "100" } });
  fireEvent.click(screen.getByRole("button", { name: /^place$/i }));
}

describe("SandboxControls", () => {
  it("renders the Virtual Capital and Place Practice Order sections", () => {
    renderWithProviders();
    expect(screen.getByText("Virtual Capital")).toBeInTheDocument();
    expect(screen.getByText("Place Practice Order")).toBeInTheDocument();
    expect(screen.getByLabelText(/Place Practice Order/i)).toBeInTheDocument();
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

  it("places a Practice order against virtual capital and shows it filled", async () => {
    renderWithProviders();
    await fillOrder();

    expect(await screen.findByText(/Order filled/i)).toBeInTheDocument();
    expect(screen.getByText(/Filled 50 @ 100/i)).toBeInTheDocument();

    // Posted to the sandbox order endpoint with the normalised payload.
    const orderCall = fetchMock.mock.calls.find((c) => String(c[0]).endsWith("/order"));
    expect(orderCall).toBeTruthy();
    const body = JSON.parse((orderCall![1] as { body: string }).body);
    expect(body).toMatchObject({ symbol: "NIFTY", exchange: "NSE", action: "BUY", quantity: 50, price: 100 });
  });

  it("surfaces a rejected order's reason (HTTP 400 with a populated order)", async () => {
    orderResponder = () => ({
      ok: false, // backend returns 400 for a rejected order
      json: async () => ({
        status: "success",
        data: { order: { order_id: "", status: "REJECTED", message: "Insufficient capital" } },
      }),
    });
    renderWithProviders();
    await fillOrder();

    expect(await screen.findByText(/Order rejected/i)).toBeInTheDocument();
    expect(screen.getByText(/Insufficient capital/i)).toBeInTheDocument();
  });

  it("shows a resting Practice order as pending rather than rejected", async () => {
    orderResponder = () => ({
      ok: true,
      json: async () => ({
        status: "success",
        data: { order: { order_id: "OID2", status: "PENDING", message: "Waiting for a matching tick" } },
      }),
    });
    renderWithProviders();
    await fillOrder();

    expect(await screen.findByText(/Order pending/i)).toBeInTheDocument();
    expect(screen.getByText(/Waiting for a matching tick/i)).toBeInTheDocument();
    expect(screen.queryByText(/Order rejected/i)).not.toBeInTheDocument();
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

  it("validates the order form before posting", async () => {
    renderWithProviders();
    // Submit with an empty symbol.
    fireEvent.change(screen.getByLabelText("Order quantity"), { target: { value: "50" } });
    fireEvent.change(screen.getByLabelText("Order price"), { target: { value: "100" } });
    fireEvent.click(screen.getByRole("button", { name: /^place$/i }));

    expect(await screen.findByText(/Symbol is required/i)).toBeInTheDocument();
    await waitFor(() =>
      expect(fetchMock.mock.calls.some((c) => String(c[0]).endsWith("/order"))).toBe(false),
    );
  });
});
