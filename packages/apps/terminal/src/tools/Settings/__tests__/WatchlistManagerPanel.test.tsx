/**
 * WatchlistManagerPanel.test — manage + Excel-import the download watchlist.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor, cleanup } from "@testing-library/react";
import "@testing-library/jest-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

vi.mock("@/services/ftApi", () => ({
  uploadExcel: vi.fn(),
}));
vi.mock("@/components/NotificationCentre/useNotificationFeed", () => ({
  emitNotification: vi.fn(),
}));

import { WatchlistManagerPanel, rowsToWatchlistEntries } from "../WatchlistManagerPanel";
import { uploadExcel } from "@/services/ftApi";
import { emitNotification } from "@/components/NotificationCentre/useNotificationFeed";

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

describe("rowsToWatchlistEntries", () => {
  it("maps case-insensitive headers, defaults interval, and counts skipped rows", () => {
    const { entries, skipped } = rowsToWatchlistEntries([
      { Symbol: "tcs", EXCHANGE: "nse" },
      { symbol: "RELIANCE", exchange: "NSE", interval: "5m" },
      { name: "no symbol column" },
    ]);
    expect(entries).toEqual([
      { symbol: "TCS", exchange: "NSE", interval: "1d" },
      { symbol: "RELIANCE", exchange: "NSE", interval: "5m" },
    ]);
    expect(skipped).toBe(1);
  });
});

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

  it("reports a PARTIAL import honestly and still refreshes the list", async () => {
    vi.mocked(uploadExcel).mockResolvedValue([
      { symbol: "TCS", exchange: "NSE" },
      { symbol: "BADSYM", exchange: "NSE" },
    ]);
    const fetchMock = vi.fn((_url: string, init?: RequestInit) => {
      if (init?.method === "POST") {
        const body = JSON.parse(String(init.body)) as { symbol: string };
        return body.symbol === "BADSYM"
          ? jsonResponse({ status: "error", message: "invalid symbol" }, 400)
          : jsonResponse({ status: "success" }, 201);
      }
      return jsonResponse({ data: [] });
    });
    vi.stubGlobal("fetch", fetchMock);

    renderPanel();
    fireEvent.change(screen.getByLabelText("Import watchlist from Excel"), {
      target: { files: [new File(["x"], "watchlist.xlsx")] },
    });

    await waitFor(() =>
      expect(emitNotification).toHaveBeenCalledWith(
        expect.objectContaining({
          category: "alert",
          title: "Watchlist import partly failed",
          body: expect.stringContaining("Added 1 symbol"),
        }),
      ),
    );
    expect(vi.mocked(emitNotification).mock.calls[0][0].body).toContain("1 failed: BADSYM");
  });

  it("imports an Excel watchlist: adds usable rows, reports skipped ones", async () => {
    vi.mocked(uploadExcel).mockResolvedValue([
      { Symbol: "TCS", Exchange: "NSE" },
      { remark: "row without symbol/exchange" },
    ]);
    const fetchMock = vi.fn((_url: string, init?: RequestInit) => {
      if (init?.method === "POST") return jsonResponse({ status: "success" }, 201);
      return jsonResponse({ data: [] });
    });
    vi.stubGlobal("fetch", fetchMock);

    renderPanel();

    const file = new File(["xlsx-bytes"], "watchlist.xlsx");
    fireEvent.change(screen.getByLabelText("Import watchlist from Excel"), {
      target: { files: [file] },
    });

    await waitFor(() => {
      expect(emitNotification).toHaveBeenCalledWith(
        expect.objectContaining({
          category: "system",
          title: "Watchlist import complete",
          body: expect.stringContaining("Added 1 symbol"),
        }),
      );
    });
    expect(vi.mocked(emitNotification).mock.calls[0][0].body).toContain("1 row skipped");

    const postCall = fetchMock.mock.calls.find(([, init]) => init?.method === "POST");
    expect(JSON.parse(String(postCall![1]!.body))).toEqual({
      symbol: "TCS",
      exchange: "NSE",
      interval: "1d",
    });
  });

  it("surfaces an import error when the sheet has no usable rows", async () => {
    vi.mocked(uploadExcel).mockResolvedValue([{ remark: "nothing useful" }]);
    vi.stubGlobal("fetch", vi.fn(() => jsonResponse({ data: [] })));

    renderPanel();

    const file = new File(["xlsx-bytes"], "watchlist.xlsx");
    fireEvent.change(screen.getByLabelText("Import watchlist from Excel"), {
      target: { files: [file] },
    });

    await waitFor(() =>
      expect(screen.getByText(/no usable rows/i)).toBeInTheDocument(),
    );
    expect(emitNotification).toHaveBeenCalledWith(
      expect.objectContaining({ category: "alert", title: "Watchlist import failed" }),
    );
  });
});
