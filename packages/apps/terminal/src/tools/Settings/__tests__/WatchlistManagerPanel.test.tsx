/**
 * WatchlistManagerPanel.test — manage the download watchlist.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor, cleanup } from "@testing-library/react";
import "@testing-library/jest-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { WatchlistManagerPanel } from "../WatchlistManagerPanel";

function jsonResponse(body: unknown, status = 200) {
  return Promise.resolve({
    ok: status < 400,
    status,
    json: () => Promise.resolve(body),
  } as Response);
}

function renderPanel() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <WatchlistManagerPanel />
    </QueryClientProvider>,
  );
}

describe("WatchlistManagerPanel", () => {
  beforeEach(() => vi.clearAllMocks());
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it("lists watchlist symbols from the backend at the /ft-api/v1 prefix", async () => {
    const fetchMock = vi.fn((_url: string) =>
      jsonResponse({
        data: [{ symbol: "RELIANCE", exchange: "NSE", interval: "1d", enabled: true }],
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    renderPanel();

    await waitFor(() => expect(screen.getByText("RELIANCE")).toBeInTheDocument());
    // Pin the URL: the historify family registers at the bare /v1 prefix —
    // a drift to /api/v1 (the recurring wiring bug) would 404 in production.
    expect(String(fetchMock.mock.calls[0][0])).toBe("/ft-api/v1/historify/watchlist");
    expect(
      screen.getByRole("button", { name: "Remove RELIANCE (NSE) from the watchlist" }),
    ).toBeInTheDocument();
  });

  it("shows an honest empty state when the watchlist has no symbols", async () => {
    vi.stubGlobal("fetch", vi.fn(() => jsonResponse({ data: [] })));

    renderPanel();

    await waitFor(() =>
      expect(screen.getByText(/no symbols yet/i)).toBeInTheDocument(),
    );
  });

  it("adds a symbol via the form (uppercased) and refreshes the list", async () => {
    const fetchMock = vi.fn((_url: string, init?: RequestInit) => {
      if (init?.method === "POST") return jsonResponse({ status: "success" }, 201);
      return jsonResponse({ data: [] });
    });
    vi.stubGlobal("fetch", fetchMock);

    renderPanel();

    fireEvent.change(screen.getByLabelText("Watchlist symbol"), { target: { value: "infy" } });
    fireEvent.click(screen.getByRole("button", { name: /^add$/i }));

    await waitFor(() => {
      const postCall = fetchMock.mock.calls.find(([, init]) => init?.method === "POST");
      expect(postCall).toBeTruthy();
      expect(String(postCall![0])).toBe("/ft-api/v1/historify/watchlist");
      expect(JSON.parse(String(postCall![1]!.body))).toEqual({
        symbol: "INFY",
        exchange: "NSE",
        interval: "1d",
      });
    });
  });

  it("keeps watchlist management local to the symbol form", async () => {
    vi.stubGlobal("fetch", vi.fn(() => jsonResponse({ data: [] })));
    const { container } = renderPanel();
    expect(screen.getByRole("button", { name: /^add$/i })).toBeInTheDocument();
    expect(container.querySelector('input[type="file"]')).toBeNull();
    expect(screen.queryByRole("button", { name: /import/i })).toBeNull();
    await waitFor(() => expect(screen.getByText(/no symbols yet/i)).toBeInTheDocument());
  });
});
