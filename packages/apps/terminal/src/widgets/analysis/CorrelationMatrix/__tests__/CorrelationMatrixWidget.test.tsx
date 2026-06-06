import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import "@testing-library/jest-dom";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------
//
// When connected, the widget fetches the live correlation matrix via
// getCorrelationMatrix and shows "Live" only when the backend reports
// is_sample_data:false. Disconnected (or backend-sample) → editable sample
// matrix with the honest "Sample data" badge.

vi.mock("@/hooks/useTrackBehavior", () => ({
  useTrackBehavior: () => vi.fn(),
}));

vi.mock("@/hooks/useBrokerConnected", () => ({
  useBrokerConnected: vi.fn().mockReturnValue(false),
}));

vi.mock("@/services/ftApi.analysis", () => ({
  getCorrelationMatrix: vi.fn(),
}));

import { useBrokerConnected } from "@/hooks/useBrokerConnected";
import { getCorrelationMatrix } from "@/services/ftApi.analysis";
import CorrelationMatrixWidget from "../CorrelationMatrixWidget";

const mockConnected = useBrokerConnected as ReturnType<typeof vi.fn>;
const mockGetMatrix = getCorrelationMatrix as ReturnType<typeof vi.fn>;

function liveResponse() {
  const symbols = ["NIFTY", "BANKNIFTY", "RELIANCE"];
  return {
    symbols,
    matrix: [
      [1.0, 0.92, 0.74],
      [0.92, 1.0, 0.69],
      [0.74, 0.69, 1.0],
    ],
    regime: "Risk-On" as const,
    regime_rationale: "breadth positive",
    vix: 13.2,
    dxy: 104.1,
    updated_at: "2026-06-06T09:30:00Z",
    is_sample_data: false,
  };
}

function renderWidget() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <CorrelationMatrixWidget />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  mockConnected.mockReturnValue(false);
  // Default: backend would serve its own sample fallback if asked.
  mockGetMatrix.mockResolvedValue({ ...liveResponse(), is_sample_data: true });
});

describe("CorrelationMatrixWidget", () => {
  it("renders widget header with title", () => {
    renderWidget();
    expect(screen.getByText("Correlation Matrix")).toBeTruthy();
  });

  it("shows the Sample data badge when disconnected", () => {
    mockConnected.mockReturnValue(false);
    renderWidget();
    expect(screen.getByText("Sample data")).toBeTruthy();
  });

  it("does not fetch the matrix when disconnected", () => {
    mockConnected.mockReturnValue(false);
    renderWidget();
    expect(mockGetMatrix).not.toHaveBeenCalled();
  });

  it("flips to a Live badge when the backend returns a genuinely-live matrix", async () => {
    mockConnected.mockReturnValue(true);
    mockGetMatrix.mockResolvedValue(liveResponse());
    renderWidget();

    await waitFor(() => expect(screen.getByText("Live")).toBeInTheDocument());
    expect(screen.queryByText("Sample data")).not.toBeInTheDocument();
    // Backend's instrument set is rendered; add control is disabled while live.
    expect(screen.getByLabelText("Add instrument to correlation matrix")).toBeDisabled();
    expect(mockGetMatrix).toHaveBeenCalled();
  });

  it("stays on Sample data when connected but the backend reports is_sample_data:true", async () => {
    mockConnected.mockReturnValue(true);
    mockGetMatrix.mockResolvedValue({ ...liveResponse(), is_sample_data: true });
    renderWidget();

    await waitFor(() => expect(mockGetMatrix).toHaveBeenCalled());
    expect(screen.getByText("Sample data")).toBeInTheDocument();
    expect(screen.queryByText("Live")).not.toBeInTheDocument();
  });

  it("Sample data badge carries an honest status role and explanatory title", () => {
    renderWidget();
    const badge = screen.getByText("Sample data");
    expect(badge.getAttribute("role")).toBe("status");
    expect(badge.getAttribute("title")).toMatch(/no live data wired yet/i);
  });

  it("does not render a live-looking refresh control implying fresh data", () => {
    renderWidget();
    expect(screen.queryByLabelText("Refresh correlation data")).toBeNull();
  });

  it("renders default 8 instruments as column headers (sample mode)", () => {
    renderWidget();
    expect(screen.getAllByText("NIFTY").length).toBeGreaterThan(0);
    expect(screen.getAllByText("GOLD").length).toBeGreaterThan(0);
    expect(screen.getAllByText("TCS").length).toBeGreaterThan(0);
  });

  it("renders matrix table with aria label", () => {
    renderWidget();
    expect(screen.getByRole("table", { name: /correlation matrix table/i })).toBeTruthy();
  });

  it("renders symbol add input", () => {
    renderWidget();
    expect(screen.getByLabelText("Add instrument to correlation matrix")).toBeTruthy();
  });

  it("adds a new symbol via Enter key (sample mode)", () => {
    renderWidget();
    const input = screen.getByLabelText("Add instrument to correlation matrix");
    fireEvent.change(input, { target: { value: "SBIN" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(screen.getAllByText("SBIN").length).toBeGreaterThan(0);
  });

  it("adds a symbol via Add button (sample mode)", () => {
    renderWidget();
    const input = screen.getByLabelText("Add instrument to correlation matrix");
    fireEvent.change(input, { target: { value: "WIPRO" } });
    fireEvent.click(screen.getByLabelText("Add instrument"));
    expect(screen.getAllByText("WIPRO").length).toBeGreaterThan(0);
  });

  it("removes a symbol via X button (sample mode)", () => {
    renderWidget();
    const removeBtn = screen.getByLabelText("Remove GOLD from matrix");
    fireEvent.click(removeBtn);
    const goldElements = screen.queryAllByText("GOLD");
    expect(goldElements.length).toBe(0);
  });

  it("renders scale legend with an accurate correlation description", () => {
    renderWidget();
    expect(screen.getByText("Scale:")).toBeTruthy();
    expect(screen.getByText("Pearson correlation of returns")).toBeTruthy();
  });

  it("has correct aria label on widget container", () => {
    renderWidget();
    expect(screen.getByLabelText("Correlation Matrix widget")).toBeTruthy();
  });

  it("diagonal cells show 1.00 (sample mode)", () => {
    renderWidget();
    const ones = screen.getAllByText("1.00");
    expect(ones.length).toBeGreaterThanOrEqual(8);
  });
});
