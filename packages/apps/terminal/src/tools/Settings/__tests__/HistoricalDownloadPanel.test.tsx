/**
 * HistoricalDownloadPanel.test — start + monitor bulk OHLCV downloads.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor, cleanup } from "@testing-library/react";
import "@testing-library/jest-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { HistoricalDownloadPanel } from "../HistoricalDownloadPanel";

function jsonResponse(body: unknown, status = 200) {
  return Promise.resolve({
    ok: status < 400,
    status,
    json: () => Promise.resolve(body),
  } as Response);
}

const RUNNING = {
  job_id: "job-1",
  status: "running",
  total: 4,
  completed: 1,
  progress_pct: 25,
  eta_seconds: 30,
  free_disk_mb: 5000,
  error: null,
  message: "Downloading…",
};

const DONE = { ...RUNNING, status: "done", completed: 4, progress_pct: 100, eta_seconds: 0 };

function renderPanel() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <HistoricalDownloadPanel />
    </QueryClientProvider>,
  );
}

describe("HistoricalDownloadPanel", () => {
  beforeEach(() => vi.restoreAllMocks());
  afterEach(() => cleanup());

  it("starts a download and shows live progress", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string) =>
        String(url).includes("/download/status")
          ? jsonResponse({ data: DONE })
          : jsonResponse({ data: RUNNING }, 202),
      ),
    );

    renderPanel();
    fireEvent.click(screen.getByRole("button", { name: /download 30d/i }));

    // After the status poll resolves, the bar reaches 100% / Complete.
    await waitFor(() =>
      expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "100"),
    );
    expect(screen.getByText(/complete/i)).toBeInTheDocument();
  });

  it("shows the time-remaining (ETA) and free-disk readout while running", async () => {
    // Mission: historical download must surface a live ETA + safety state.
    const running = { ...RUNNING, eta_seconds: 90 }; // 90s -> "1m 30s"
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string) =>
        String(url).includes("/download/status")
          ? jsonResponse({ data: running })
          : jsonResponse({ data: running }, 202),
      ),
    );

    renderPanel();
    fireEvent.click(screen.getByRole("button", { name: /download 30d/i }));

    // ETA is formatted (90s -> 1m 30s) and the disk-safety free space is shown.
    await waitFor(() => expect(screen.getByText(/ETA\s*1m 30s/i)).toBeInTheDocument());
    expect(screen.getByText(/5000 MB free/i)).toBeInTheDocument();
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "25");
  });

  it("surfaces the disk-safety refusal message", async () => {
    const refused = {
      ...RUNNING,
      status: "refused",
      message: "Refused: only 100 MB free (need 500 MB). Free up disk and retry.",
    };
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string) =>
        String(url).includes("/download/status")
          ? jsonResponse({ data: refused })
          : jsonResponse({ data: refused }, 507),
      ),
    );

    renderPanel();
    fireEvent.click(screen.getByRole("button", { name: /download 30d/i }));

    await waitFor(() => expect(screen.getByText(/free up disk and retry/i)).toBeInTheDocument());
  });
});
