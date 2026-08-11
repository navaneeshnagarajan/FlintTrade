import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { mockUseQuery, mockRefetch } = vi.hoisted(() => ({
  mockUseQuery: vi.fn(),
  mockRefetch: vi.fn(),
}));

vi.mock("@tanstack/react-query", () => ({
  useQuery: mockUseQuery,
}));

vi.mock("@/services/api", () => ({
  searchSymbol: vi.fn(),
}));

import { useSymbolSearch } from "../useSymbolSearch";

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((resolvePromise) => {
    resolve = resolvePromise;
  });
  return { promise, resolve };
}

describe("useSymbolSearch retry attempt identity", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockUseQuery.mockReturnValue({
      data: [],
      isLoading: false,
      isError: true,
      refetch: mockRefetch,
    });
  });

  it("does not let an older same-query retry clear a newer retry", async () => {
    const first = deferred<unknown>();
    const second = deferred<unknown>();
    mockRefetch
      .mockReturnValueOnce(first.promise)
      .mockReturnValueOnce(second.promise);
    vi.useFakeTimers();

    const { result } = renderHook(() => useSymbolSearch("REL"));
    act(() => {
      vi.advanceTimersByTime(350);
    });
    vi.useRealTimers();

    let firstRetry: Promise<unknown> | undefined;
    act(() => {
      firstRetry = result.current.retry();
    });
    expect(result.current.isRetrying).toBe(true);

    let secondRetry: Promise<unknown> | undefined;
    act(() => {
      secondRetry = result.current.retry();
    });
    expect(result.current.isRetrying).toBe(true);

    first.resolve(undefined);
    await act(async () => {
      await firstRetry;
    });
    const remainedRetryingAfterOlderCompletion = result.current.isRetrying;

    second.resolve(undefined);
    await act(async () => {
      await secondRetry;
    });

    expect(remainedRetryingAfterOlderCompletion).toBe(true);
    expect(result.current.isRetrying).toBe(false);
  });
});
