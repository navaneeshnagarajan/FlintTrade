import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import "@testing-library/jest-dom";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

vi.mock("@/services/ftApi.data", () => ({
  captureHistoricalChain: vi.fn(),
  getHistoricalExpiries: vi.fn(),
  getHistoricalChain: vi.fn(),
}));

import {
  captureHistoricalChain,
  getHistoricalExpiries,
  getHistoricalChain,
} from "@/services/ftApi.data";
import HistoricalChainWidget from "../HistoricalChainWidget";

const mockExpiries = getHistoricalExpiries as ReturnType<typeof vi.fn>;
const mockChain = getHistoricalChain as ReturnType<typeof vi.fn>;
const mockCapture = captureHistoricalChain as ReturnType<typeof vi.fn>;

function chainRows() {
  return [
    { captured_at: "2026-03-26T15:30:00", symbol: "NIFTY", exchange: "NFO", expiry_date: "26MAR26", strike: 22000, option_type: "CE", oi: 120000, volume: 45000, ltp: 180.5, iv: 14.2 },
    { captured_at: "2026-03-26T15:30:00", symbol: "NIFTY", exchange: "NFO", expiry_date: "26MAR26", strike: 22000, option_type: "PE", oi: 98000, volume: 38000, ltp: 165.0, iv: 14.8 },
    { captured_at: "2026-03-26T15:30:00", symbol: "NIFTY", exchange: "NFO", expiry_date: "26MAR26", strike: 22100, option_type: "CE", oi: 80000, volume: 30000, ltp: 120.0, iv: 13.9 },
  ];
}

function renderWidget() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <HistoricalChainWidget />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  mockExpiries.mockResolvedValue({ symbol: "NIFTY", exchange: "NFO", expiries: [] });
  mockChain.mockResolvedValue({ symbol: "NIFTY", exchange: "NFO", expiry: "", chain: [] });
  mockCapture.mockResolvedValue({
    symbol: "NIFTY",
    exchange: "NFO",
    expiry: "2026-03-26",
    rows_inserted: 2,
    captured: true,
  });
});

describe("HistoricalChainWidget", () => {
  it("renders the widget title", () => {
    renderWidget();
    expect(screen.getByText("Historical Chain")).toBeTruthy();
  });

  it("shows an honest empty state when nothing has been archived (no sample data)", async () => {
    mockExpiries.mockResolvedValue({ symbol: "NIFTY", exchange: "NFO", expiries: [] });
    renderWidget();
    await waitFor(() =>
      expect(screen.getByText(/no historical chains captured for NIFTY yet/i)).toBeInTheDocument(),
    );
    // Never fetches a chain when there are no archived expiries.
    expect(mockChain).not.toHaveBeenCalled();
  });

  it("lists archived expiries and renders the chain grouped by strike", async () => {
    mockExpiries.mockResolvedValue({ symbol: "NIFTY", exchange: "NFO", expiries: ["26MAR26", "24APR26"] });
    mockChain.mockResolvedValue({ symbol: "NIFTY", exchange: "NFO", expiry: "24APR26", chain: chainRows() });
    renderWidget();

    // Fetches the newest expiry's chain by default and renders both strikes.
    await waitFor(() => expect(screen.getByText("22000")).toBeInTheDocument());
    expect(screen.getByText("22100")).toBeInTheDocument();
    expect(mockChain).toHaveBeenCalledWith("NIFTY", "24APR26", "NFO");
    // CALLS / PUTS column groups are present.
    expect(screen.getByText("CALLS")).toBeInTheDocument();
    expect(screen.getByText("PUTS")).toBeInTheDocument();
  });

  it("refetches the chain when a different archived expiry is selected", async () => {
    mockExpiries.mockResolvedValue({ symbol: "NIFTY", exchange: "NFO", expiries: ["26MAR26", "24APR26"] });
    mockChain.mockResolvedValue({ symbol: "NIFTY", exchange: "NFO", expiry: "24APR26", chain: chainRows() });
    renderWidget();

    await waitFor(() => expect(screen.getByText("22000")).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText(/select archived expiry/i), { target: { value: "26MAR26" } });
    await waitFor(() => expect(mockChain).toHaveBeenCalledWith("NIFTY", "26MAR26", "NFO"));
  });

  it("defaults to the newest archived expiry", async () => {
    mockExpiries.mockResolvedValue({
      symbol: "NIFTY",
      exchange: "NFO",
      expiries: ["2026-03-26", "2026-04-02"],
    });
    mockChain.mockResolvedValue({
      symbol: "NIFTY",
      exchange: "NFO",
      expiry: "2026-04-02",
      chain: chainRows(),
    });

    renderWidget();

    await waitFor(() =>
      expect(mockChain).toHaveBeenCalledWith("NIFTY", "2026-04-02", "NFO"),
    );
  });

  it("captures a broker option-chain snapshot and refreshes the archive", async () => {
    mockExpiries
      .mockResolvedValueOnce({ symbol: "NIFTY", exchange: "NFO", expiries: [] })
      .mockResolvedValue({
        symbol: "NIFTY",
        exchange: "NFO",
        expiries: ["2026-03-26"],
      });
    renderWidget();

    fireEvent.change(screen.getByLabelText(/expiry to capture/i), {
      target: { value: "2026-03-26" },
    });
    fireEvent.click(screen.getByRole("button", { name: /capture/i }));

    await waitFor(() =>
      expect(mockCapture).toHaveBeenCalledWith("NIFTY", "2026-03-26", "NFO"),
    );
    expect(await screen.findByText(/captured 2 rows for 2026-03-26/i)).toBeInTheDocument();
    await waitFor(() =>
      expect(mockChain).toHaveBeenCalledWith("NIFTY", "2026-03-26", "NFO"),
    );
  });

  it("surfaces capture failures", async () => {
    mockCapture.mockRejectedValue(new Error("OpenAlgo is not connected"));
    renderWidget();

    fireEvent.change(screen.getByLabelText(/expiry to capture/i), {
      target: { value: "2026-03-26" },
    });
    fireEvent.click(screen.getByRole("button", { name: /capture/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Capture failed: OpenAlgo is not connected",
    );
  });

  it("keeps the capture identity stable while a request is pending", async () => {
    let resolveCapture: ((value: {
      symbol: string;
      exchange: string;
      expiry: string;
      rows_inserted: number;
      captured: boolean;
    }) => void) | undefined;
    mockCapture.mockReturnValue(new Promise((resolve) => {
      resolveCapture = resolve;
    }));
    renderWidget();

    const expiryInput = screen.getByLabelText(/expiry to capture/i);
    fireEvent.click(screen.getByRole("button", { name: /selected symbol: NIFTY/i }));
    expect(screen.getByRole("option", { name: "BANKNIFTY" })).toBeInTheDocument();
    fireEvent.change(expiryInput, { target: { value: "2026-03-26" } });
    fireEvent.click(screen.getByRole("button", { name: "Capture" }));

    const pendingButton = await screen.findByRole("button", { name: /capturing/i });
    expect(pendingButton).toBeDisabled();
    expect(pendingButton).toHaveAttribute("aria-busy", "true");
    expect(expiryInput).toBeDisabled();
    expect(screen.getByRole("button", { name: /selected symbol: NIFTY/i })).toBeDisabled();
    expect(screen.queryByRole("option", { name: "BANKNIFTY" })).not.toBeInTheDocument();
    expect(mockCapture).toHaveBeenCalledTimes(1);

    resolveCapture?.({
      symbol: "NIFTY",
      exchange: "NFO",
      expiry: "2026-03-26",
      rows_inserted: 2,
      captured: true,
    });
    expect(await screen.findByText(/captured 2 rows for 2026-03-26/i)).toBeInTheDocument();
  });

  it("opens the symbol menu and switches symbol", async () => {
    renderWidget();
    fireEvent.click(screen.getByRole("button", { name: /selected symbol: NIFTY/i }));
    fireEvent.click(screen.getByRole("option", { name: "BANKNIFTY" }));
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /selected symbol: BANKNIFTY/i })).toBeInTheDocument(),
    );
    expect(mockExpiries).toHaveBeenCalledWith("BANKNIFTY", "NFO");
  });
});
