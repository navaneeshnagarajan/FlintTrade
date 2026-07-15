import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  getForwardTrades,
  getRunningStrategies,
  getStrategies,
  startStrategy,
  stopStrategy,
} from "@/services/ftApi";
import { useAuthStore } from "@/stores/authStore";
import { ForwardTestSection } from "../ForwardTest";

vi.mock("@/services/ftApi", () => ({
  getForwardTrades: vi.fn(),
  getRunningStrategies: vi.fn(),
  getStrategies: vi.fn(),
  startStrategy: vi.fn(),
  stopStrategy: vi.fn(),
}));

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((nextResolve) => {
    resolve = nextResolve;
  });
  return { promise, resolve };
}

function renderForwardTest() {
  const queryClient = new QueryClient({
    defaultOptions: {
      mutations: { retry: false },
      queries: { retry: false },
    },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <ForwardTestSection />
    </QueryClientProvider>,
  );
}

describe("ForwardTestSection", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useAuthStore.setState({
      status: "logged-in",
      token: "token-1",
      username: "alice",
      sessionGeneration: 7,
    });
    vi.mocked(getStrategies).mockResolvedValue([
      {
        name: "mean-reversion",
        description: "Mean reversion",
        category: "Technical",
        parameters: [],
      },
    ]);
    vi.mocked(getRunningStrategies).mockResolvedValue([
      {
        name: "mean-reversion",
        symbol: "NIFTY",
        exchange: "NFO",
        status: "running",
        tick_count: 5,
        started_at: "2026-07-15T10:00:00Z",
        virtual_pnl: 125,
      },
    ]);
    vi.mocked(startStrategy).mockResolvedValue({ status: "started" });
    vi.mocked(stopStrategy).mockResolvedValue({ status: "stopped" });
  });

  it("does not publish a stopped summary after the auth session changes during trade loading", async () => {
    const pendingTrades =
      deferred<Awaited<ReturnType<typeof getForwardTrades>>>();
    vi.mocked(getForwardTrades)
      .mockResolvedValueOnce([])
      .mockReturnValueOnce(pendingTrades.promise);
    renderForwardTest();

    await screen.findByText("Select a strategy…");
    fireEvent.click(screen.getAllByRole("combobox")[0]);
    fireEvent.click(
      await screen.findByRole("option", { name: /mean-reversion/i }),
    );
    fireEvent.click(
      screen.getByRole("button", { name: /start forward test/i }),
    );

    fireEvent.click(await screen.findByRole("button", { name: /^stop$/i }));
    await waitFor(() => expect(getForwardTrades).toHaveBeenCalledTimes(2));

    act(() => {
      useAuthStore.setState((state) => ({
        sessionGeneration: state.sessionGeneration + 1,
      }));
    });
    await act(async () => {
      pendingTrades.resolve([]);
      await pendingTrades.promise;
    });

    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: /^stop$/i }),
      ).toBeInTheDocument(),
    );
    expect(screen.queryByText("Session Summary")).not.toBeInTheDocument();
  });
});
