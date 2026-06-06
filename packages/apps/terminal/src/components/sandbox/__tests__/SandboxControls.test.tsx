/**
 * SandboxControls.test.tsx — Renders sandbox settings panel + paper-order flow.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

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

const fetchMock = vi.fn(async (url: unknown, opts?: { body?: string }) => {
  const u = String(url);
  if (u.endsWith("/order")) {
    return orderResponder(opts?.body ? JSON.parse(opts.body) : {});
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
  it("renders the Virtual Capital and Place Paper Order sections", () => {
    renderWithProviders();
    expect(screen.getByText("Virtual Capital")).toBeInTheDocument();
    expect(screen.getByText("Place Paper Order")).toBeInTheDocument();
    expect(screen.getByText("Adjust Capital")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /export data/i })).toBeInTheDocument();
  });

  it("places a paper order against virtual capital and shows it filled", async () => {
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
