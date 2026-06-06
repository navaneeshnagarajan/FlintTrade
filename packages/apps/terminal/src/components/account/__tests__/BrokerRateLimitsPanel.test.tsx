import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

vi.mock("@/services/gatewayApi", () => ({
  gatewayApi: {
    getRateLimits: vi.fn(),
    setRateLimit: vi.fn(),
  },
}));
import { gatewayApi } from "@/services/gatewayApi";
import { BrokerRateLimitsPanel } from "../BrokerRateLimitsPanel";

const mockGet = gatewayApi.getRateLimits as unknown as ReturnType<typeof vi.fn>;
const mockSet = gatewayApi.setRateLimit as unknown as ReturnType<typeof vi.fn>;

function renderPanel() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <BrokerRateLimitsPanel />
    </QueryClientProvider>,
  );
}

describe("BrokerRateLimitsPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockGet.mockResolvedValue({ openalgo: { order: 10, data: 5 } });
    mockSet.mockResolvedValue({ openalgo: { order: 3, data: 5 } });
  });

  it("shows each broker's live order/data limits", async () => {
    renderPanel();
    expect(await screen.findByText("openalgo")).toBeInTheDocument();
    expect(screen.getByLabelText(/openalgo order rate/i)).toHaveValue("10");
    expect(screen.getByLabelText(/openalgo data rate/i)).toHaveValue("5");
  });

  it("saves an edited limit through the gateway", async () => {
    renderPanel();
    await screen.findByText("openalgo");

    fireEvent.change(screen.getByLabelText(/openalgo order rate/i), { target: { value: "3" } });
    fireEvent.click(screen.getByRole("button", { name: /save openalgo rate limits/i }));

    await waitFor(() => expect(mockSet).toHaveBeenCalledWith("openalgo", 3, 5));
  });

  it("shows an honest empty state when no limiter is active", async () => {
    mockGet.mockResolvedValue({});
    renderPanel();
    expect(await screen.findByText(/No rate-limited brokers connected/i)).toBeInTheDocument();
  });

  it("blocks saving a negative rate", async () => {
    renderPanel();
    await screen.findByText("openalgo");
    fireEvent.change(screen.getByLabelText(/openalgo order rate/i), { target: { value: "-2" } });
    expect(screen.getByRole("button", { name: /save openalgo rate limits/i })).toBeDisabled();
    expect(mockSet).not.toHaveBeenCalled();
  });
});
