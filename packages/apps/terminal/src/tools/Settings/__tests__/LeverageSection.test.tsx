/**
 * LeverageSection.test — FT-SET-004 blank-pane lock.
 *
 * Settings `#leverage` must show real snapshot tiles or the honest empty
 * `Leverage settings unavailable.` plus Retry. Returning null (unsupported
 * broker, missing snapshot, load failure) leaves a highlighted tab over a
 * blank pane — that is the regression these cases pin.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import "@testing-library/jest-dom";

import type { BrokerCapabilities, LeverageSettings } from "@/types/api";

const caps = vi.hoisted(() => ({
  data: undefined as BrokerCapabilities | undefined,
  isLoading: false,
  isError: false,
  refetch: vi.fn(),
}));

const api = vi.hoisted(() => ({
  getLeverageSettings: vi.fn(),
}));

vi.mock("@/hooks/useBrokerCapabilities", () => ({
  useBrokerCapabilities: () => ({
    data: caps.data,
    isLoading: caps.isLoading,
    isError: caps.isError,
    refetch: caps.refetch,
  }),
}));

vi.mock("@/services/api", () => ({
  getLeverageSettings: api.getLeverageSettings,
}));

import { LeverageSection } from "../LeverageSection";

const unsupportedCaps: BrokerCapabilities = {
  broker_name: "Zerodha",
  broker_type: "equity",
  supported_exchanges: ["NSE"],
  features: {
    market_protection: false,
    leverage: false,
    bracket_orders: false,
    cover_orders: false,
  },
};

const supportedCaps: BrokerCapabilities = {
  ...unsupportedCaps,
  broker_name: "Binance",
  broker_type: "crypto",
  supported_exchanges: ["BINANCE"],
  features: {
    ...unsupportedCaps.features,
    leverage: true,
  },
};

function renderSection() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  return render(<LeverageSection />, { wrapper });
}

function expectHonestEmpty() {
  expect(screen.getByText("Leverage settings unavailable.")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();
}

describe("LeverageSection blank-pane lock (FT-SET-004)", () => {
  beforeEach(() => {
    caps.data = undefined;
    caps.isLoading = false;
    caps.isError = false;
    caps.refetch.mockReset().mockResolvedValue(undefined);
    api.getLeverageSettings.mockReset();
  });

  it("REGRESSION: unsupported broker shows honest empty + Retry, never a blank pane", async () => {
    caps.data = unsupportedCaps;

    const { container } = renderSection();

    await waitFor(() => expectHonestEmpty());
    expect(container.textContent?.trim().length).toBeGreaterThan(0);
    expect(screen.queryByText("Available Margin")).not.toBeInTheDocument();
    expect(api.getLeverageSettings).not.toHaveBeenCalled();
  });

  it("REGRESSION: missing capabilities snapshot shows honest empty + Retry", async () => {
    caps.data = undefined;

    renderSection();

    await waitFor(() => expectHonestEmpty());
  });

  it("REGRESSION: capabilities load failure shows honest empty + Retry", async () => {
    caps.isError = true;

    renderSection();

    await waitFor(() => expectHonestEmpty());
  });

  it("REGRESSION: leverage load failure shows honest empty + Retry", async () => {
    caps.data = supportedCaps;
    api.getLeverageSettings.mockRejectedValue(new Error("margin snapshot failed"));

    renderSection();

    await waitFor(() => expectHonestEmpty());
  });

  it("REGRESSION: supported broker with an empty snapshot shows honest empty + Retry", async () => {
    caps.data = supportedCaps;
    api.getLeverageSettings.mockResolvedValue({} satisfies LeverageSettings);

    renderSection();

    await waitFor(() => expectHonestEmpty());
  });

  it("Retry refetches capabilities when leverage cannot be shown", async () => {
    caps.data = unsupportedCaps;

    renderSection();
    await waitFor(() => expectHonestEmpty());

    fireEvent.click(screen.getByRole("button", { name: "Retry" }));

    expect(caps.refetch).toHaveBeenCalledTimes(1);
  });

  it("Retry refetches the margin snapshot after a load failure", async () => {
    caps.data = supportedCaps;
    api.getLeverageSettings
      .mockRejectedValueOnce(new Error("margin snapshot failed"))
      .mockResolvedValueOnce({
        available: 50_000,
        used: 10_000,
        total: 60_000,
        leverage_ratio: 0.1667,
      } satisfies LeverageSettings);

    renderSection();
    await waitFor(() => expectHonestEmpty());

    fireEvent.click(screen.getByRole("button", { name: "Retry" }));

    await waitFor(() => {
      expect(screen.getByText("Available Margin")).toBeInTheDocument();
    });
    expect(screen.getByText("50000")).toBeInTheDocument();
    expect(screen.queryByText("Leverage settings unavailable.")).not.toBeInTheDocument();
    expect(api.getLeverageSettings).toHaveBeenCalledTimes(2);
  });

  it("renders real margin tiles when the broker snapshot is available", async () => {
    caps.data = supportedCaps;
    api.getLeverageSettings.mockResolvedValue({
      available: 50_000,
      used: 10_000,
      total: 60_000,
      leverage_ratio: 0.1667,
    } satisfies LeverageSettings);

    renderSection();

    await waitFor(() => {
      expect(screen.getByText("Available Margin")).toBeInTheDocument();
    });
    expect(screen.getByText("Used Margin")).toBeInTheDocument();
    expect(screen.getByText("Utilisation")).toBeInTheDocument();
    expect(screen.queryByText("Leverage settings unavailable.")).not.toBeInTheDocument();
  });

  it("renders leverage-ratio tiles when the snapshot has no margin fields", async () => {
    caps.data = supportedCaps;
    api.getLeverageSettings.mockResolvedValue({
      leverage: 5,
      max_leverage: 20,
      margin_mode: "cross",
    } satisfies LeverageSettings);

    renderSection();

    await waitFor(() => {
      expect(screen.getByText("Current Leverage")).toBeInTheDocument();
    });
    expect(screen.getByText("5x")).toBeInTheDocument();
    expect(screen.getByText("20x")).toBeInTheDocument();
    expect(screen.getByText("cross")).toBeInTheDocument();
  });

  it("shows a loading status instead of a blank pane while capabilities load", () => {
    caps.isLoading = true;

    renderSection();

    expect(screen.getByText("Checking broker capabilities...")).toBeInTheDocument();
    expect(screen.queryByText("Leverage settings unavailable.")).not.toBeInTheDocument();
  });
});
