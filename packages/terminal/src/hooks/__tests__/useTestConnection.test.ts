/**
 * useTestConnection.test.ts
 *
 * Tests for the useTestConnection hook.
 *
 * Strategy:
 *   - vi.stubGlobal("fetch", ...) replaces the global fetch with a spy so we
 *     control every network response without making real HTTP calls.
 *   - AbortSignal.timeout is stubbed once so jsdom's missing implementation
 *     does not break the hook constructor.
 *   - renderHook from @testing-library/react is used throughout.
 *   - act() wraps every state-changing async call so React flushes updates
 *     before we inspect the result.
 *
 * Arrange-Act-Assert pattern is applied to every test case.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useTestConnection } from "../useTestConnection";
import type { TestConnectionStatus } from "../useTestConnection";

// ---------------------------------------------------------------------------
// Global stubs
// ---------------------------------------------------------------------------

// AbortSignal.timeout may not be available in jsdom. Stub it once globally
// so the hook can always call it without a TypeError.
if (!("timeout" in AbortSignal)) {
  const orig = AbortSignal;
  vi.stubGlobal("AbortSignal", Object.assign(
    Object.create(orig),
    { timeout: (_ms: number) => new AbortController().signal }
  ));
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const HOST = "http://localhost:5000";
const API_KEY = "test-api-key-12345";

/** Build a minimal Response-like object accepted by the fetch mock. */
function makeResponse(
  status: number,
  ok = status >= 200 && status < 300,
): Response {
  return { ok, status } as unknown as Response;
}

// ---------------------------------------------------------------------------
// Setup / teardown
// ---------------------------------------------------------------------------

beforeEach(() => {
  vi.restoreAllMocks();
});

afterEach(() => {
  vi.restoreAllMocks();
});

// ---------------------------------------------------------------------------
// Initial state
// ---------------------------------------------------------------------------

describe("useTestConnection — initial state", () => {
  it("starts with status 'idle'", () => {
    // Arrange + Act
    const { result } = renderHook(() => useTestConnection());
    // Assert
    expect(result.current.status).toBe<TestConnectionStatus>("idle");
  });

  it("starts with an empty message", () => {
    // Arrange + Act
    const { result } = renderHook(() => useTestConnection());
    // Assert
    expect(result.current.message).toBe("");
  });

  it("exposes testConnection and reset as functions", () => {
    const { result } = renderHook(() => useTestConnection());
    expect(typeof result.current.testConnection).toBe("function");
    expect(typeof result.current.reset).toBe("function");
  });
});

// ---------------------------------------------------------------------------
// Successful connection (HTTP 200)
// ---------------------------------------------------------------------------

describe("useTestConnection — successful connection", () => {
  it("sets status to 'ok' when the API responds with 200", async () => {
    // Arrange
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(makeResponse(200)));
    const { result } = renderHook(() => useTestConnection());

    // Act
    await act(async () => {
      await result.current.testConnection(HOST, API_KEY);
    });

    // Assert
    expect(result.current.status).toBe<TestConnectionStatus>("ok");
  });

  it("sets message to 'Connected successfully' on 200", async () => {
    // Arrange
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(makeResponse(200)));
    const { result } = renderHook(() => useTestConnection());

    // Act
    await act(async () => {
      await result.current.testConnection(HOST, API_KEY);
    });

    // Assert
    expect(result.current.message).toBe("Connected successfully");
  });

  it("calls fetch with the correct URL and POST method", async () => {
    // Arrange
    const mockFetch = vi.fn().mockResolvedValue(makeResponse(200));
    vi.stubGlobal("fetch", mockFetch);
    const { result } = renderHook(() => useTestConnection());

    // Act
    await act(async () => {
      await result.current.testConnection(HOST, API_KEY);
    });

    // Assert
    expect(mockFetch).toHaveBeenCalledOnce();
    const [url, options] = mockFetch.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("http://localhost:5000/api/v1/ping");
    expect(options.method).toBe("POST");
  });

  it("sends the apiKey in the request body as 'apikey'", async () => {
    // Arrange
    const mockFetch = vi.fn().mockResolvedValue(makeResponse(200));
    vi.stubGlobal("fetch", mockFetch);
    const { result } = renderHook(() => useTestConnection());

    // Act
    await act(async () => {
      await result.current.testConnection(HOST, API_KEY);
    });

    // Assert
    const [, options] = mockFetch.mock.calls[0] as [string, RequestInit];
    const body = JSON.parse(options.body as string) as Record<string, string>;
    expect(body.apikey).toBe(API_KEY);
  });

  it("strips a trailing slash from the host before constructing the URL", async () => {
    // Arrange
    const mockFetch = vi.fn().mockResolvedValue(makeResponse(200));
    vi.stubGlobal("fetch", mockFetch);
    const { result } = renderHook(() => useTestConnection());

    // Act
    await act(async () => {
      await result.current.testConnection("http://localhost:5000/", API_KEY);
    });

    // Assert — no double slash
    const [url] = mockFetch.mock.calls[0] as [string];
    expect(url).toBe("http://localhost:5000/api/v1/ping");
    expect(url).not.toContain("//api");
  });
});

// ---------------------------------------------------------------------------
// Loading state during request
// ---------------------------------------------------------------------------

describe("useTestConnection — loading state", () => {
  it("transitions to 'testing' while the request is in-flight", async () => {
    // Arrange — a promise we control manually
    let resolveRequest!: (v: Response) => void;
    const pendingRequest = new Promise<Response>((res) => {
      resolveRequest = res;
    });
    vi.stubGlobal("fetch", vi.fn().mockReturnValue(pendingRequest));
    const { result } = renderHook(() => useTestConnection());

    // Act — start the connection test but do NOT await it
    act(() => {
      void result.current.testConnection(HOST, API_KEY);
    });

    // Assert — still in-flight → status should be 'testing'
    expect(result.current.status).toBe<TestConnectionStatus>("testing");

    // Cleanup — resolve so React doesn't leave pending state warnings
    await act(async () => {
      resolveRequest(makeResponse(200));
      await pendingRequest;
    });
  });

  it("clears the previous message when a new test starts", async () => {
    // Arrange — first call fails, second call succeeds
    const mockFetch = vi
      .fn()
      .mockResolvedValueOnce(makeResponse(401))
      .mockResolvedValueOnce(makeResponse(200));
    vi.stubGlobal("fetch", mockFetch);
    const { result } = renderHook(() => useTestConnection());

    // First call to get a non-empty message
    await act(async () => {
      await result.current.testConnection(HOST, API_KEY);
    });
    expect(result.current.message).not.toBe("");

    // Act — second call begins → message should clear
    let resolveSecond!: (v: Response) => void;
    const secondRequest = new Promise<Response>((res) => {
      resolveSecond = res;
    });
    mockFetch.mockReturnValueOnce(secondRequest);
    act(() => {
      void result.current.testConnection(HOST, API_KEY);
    });

    // Assert — message is empty while second request is in-flight
    expect(result.current.message).toBe("");

    // Cleanup
    await act(async () => {
      resolveSecond(makeResponse(200));
      await secondRequest;
    });
  });
});

// ---------------------------------------------------------------------------
// Error cases — server-side HTTP errors
// ---------------------------------------------------------------------------

describe("useTestConnection — HTTP error responses", () => {
  it("sets status to 'error' when the server returns 401 (invalid API key)", async () => {
    // Arrange
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(makeResponse(401, false)));
    const { result } = renderHook(() => useTestConnection());

    // Act
    await act(async () => {
      await result.current.testConnection(HOST, "bad-key");
    });

    // Assert
    expect(result.current.status).toBe<TestConnectionStatus>("error");
  });

  it("includes the HTTP status code in the error message for 401", async () => {
    // Arrange
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(makeResponse(401, false)));
    const { result } = renderHook(() => useTestConnection());

    // Act
    await act(async () => {
      await result.current.testConnection(HOST, "bad-key");
    });

    // Assert — "Server returned 401"
    expect(result.current.message).toContain("401");
  });

  it("sets status to 'error' when the server returns 500", async () => {
    // Arrange
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(makeResponse(500, false)));
    const { result } = renderHook(() => useTestConnection());

    // Act
    await act(async () => {
      await result.current.testConnection(HOST, API_KEY);
    });

    // Assert
    expect(result.current.status).toBe<TestConnectionStatus>("error");
    expect(result.current.message).toContain("500");
  });

  it("sets status to 'error' for a 403 Forbidden response", async () => {
    // Arrange
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(makeResponse(403, false)));
    const { result } = renderHook(() => useTestConnection());

    // Act
    await act(async () => {
      await result.current.testConnection(HOST, API_KEY);
    });

    // Assert
    expect(result.current.status).toBe<TestConnectionStatus>("error");
    expect(result.current.message).toContain("403");
  });
});

// ---------------------------------------------------------------------------
// Error cases — network failures
// ---------------------------------------------------------------------------

describe("useTestConnection — network failure", () => {
  it("sets status to 'error' when fetch throws a network error", async () => {
    // Arrange
    vi.stubGlobal(
      "fetch",
      vi.fn().mockRejectedValue(new Error("Network request failed")),
    );
    const { result } = renderHook(() => useTestConnection());

    // Act
    await act(async () => {
      await result.current.testConnection(HOST, API_KEY);
    });

    // Assert
    expect(result.current.status).toBe<TestConnectionStatus>("error");
  });

  it("uses the Error.message in the error message field", async () => {
    // Arrange
    vi.stubGlobal(
      "fetch",
      vi.fn().mockRejectedValue(new Error("Network request failed")),
    );
    const { result } = renderHook(() => useTestConnection());

    // Act
    await act(async () => {
      await result.current.testConnection(HOST, API_KEY);
    });

    // Assert
    expect(result.current.message).toBe("Network request failed");
  });

  it("uses a fallback message for non-Error thrown values", async () => {
    // Arrange — throw a plain string (not an Error instance)
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue("some string error"));
    const { result } = renderHook(() => useTestConnection());

    // Act
    await act(async () => {
      await result.current.testConnection(HOST, API_KEY);
    });

    // Assert — hook falls back to the generic string
    expect(result.current.status).toBe<TestConnectionStatus>("error");
    expect(result.current.message).toBe("Connection failed");
  });
});

// ---------------------------------------------------------------------------
// Timeout simulation
// ---------------------------------------------------------------------------

describe("useTestConnection — timeout", () => {
  it("sets status to 'error' when fetch throws an AbortError (timeout)", async () => {
    // Arrange — AbortError is what the browser throws when AbortSignal fires.
    // In jsdom, DOMException does not extend Error, so the hook's catch block
    // falls back to the generic "Connection failed" message rather than using
    // err.message. The critical behavior to test is that status becomes "error".
    const abortError = new DOMException(
      "The operation was aborted.",
      "AbortError",
    );
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(abortError));
    const { result } = renderHook(() => useTestConnection());

    // Act
    await act(async () => {
      await result.current.testConnection(HOST, API_KEY);
    });

    // Assert — status must be error regardless of the exact message
    expect(result.current.status).toBe<TestConnectionStatus>("error");
    expect(result.current.message.length).toBeGreaterThan(0);
  });

  it("sets status to 'error' when fetch throws a TimeoutError", async () => {
    // Arrange — some environments throw a TimeoutError instead
    const timeoutError = new DOMException(
      "signal timed out",
      "TimeoutError",
    );
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(timeoutError));
    const { result } = renderHook(() => useTestConnection());

    // Act
    await act(async () => {
      await result.current.testConnection(HOST, API_KEY);
    });

    // Assert
    expect(result.current.status).toBe<TestConnectionStatus>("error");
  });
});

// ---------------------------------------------------------------------------
// reset()
// ---------------------------------------------------------------------------

describe("useTestConnection — reset", () => {
  it("resets status to 'idle' after a successful connection", async () => {
    // Arrange
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(makeResponse(200)));
    const { result } = renderHook(() => useTestConnection());
    await act(async () => {
      await result.current.testConnection(HOST, API_KEY);
    });
    expect(result.current.status).toBe("ok");

    // Act
    act(() => {
      result.current.reset();
    });

    // Assert
    expect(result.current.status).toBe<TestConnectionStatus>("idle");
  });

  it("resets status to 'idle' after an error", async () => {
    // Arrange
    vi.stubGlobal(
      "fetch",
      vi.fn().mockRejectedValue(new Error("connection refused")),
    );
    const { result } = renderHook(() => useTestConnection());
    await act(async () => {
      await result.current.testConnection(HOST, API_KEY);
    });
    expect(result.current.status).toBe("error");

    // Act
    act(() => {
      result.current.reset();
    });

    // Assert
    expect(result.current.status).toBe<TestConnectionStatus>("idle");
  });

  it("clears the message on reset", async () => {
    // Arrange
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(makeResponse(200)));
    const { result } = renderHook(() => useTestConnection());
    await act(async () => {
      await result.current.testConnection(HOST, API_KEY);
    });
    expect(result.current.message).toBe("Connected successfully");

    // Act
    act(() => {
      result.current.reset();
    });

    // Assert
    expect(result.current.message).toBe("");
  });

  it("reset is a no-op when status is already 'idle'", () => {
    // Arrange
    const { result } = renderHook(() => useTestConnection());
    // Act + Assert — no error thrown
    expect(() => {
      act(() => {
        result.current.reset();
      });
    }).not.toThrow();
    expect(result.current.status).toBe<TestConnectionStatus>("idle");
    expect(result.current.message).toBe("");
  });
});

// ---------------------------------------------------------------------------
// Stable references (useCallback identity)
// ---------------------------------------------------------------------------

describe("useTestConnection — stable function references", () => {
  it("testConnection reference is stable across re-renders", async () => {
    // Arrange
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(makeResponse(200)));
    const { result, rerender } = renderHook(() => useTestConnection());
    const firstRef = result.current.testConnection;

    // Act
    await act(async () => {
      await result.current.testConnection(HOST, API_KEY);
    });
    rerender();

    // Assert — same reference (useCallback with no deps)
    expect(result.current.testConnection).toBe(firstRef);
  });

  it("reset reference is stable across re-renders", () => {
    // Arrange
    const { result, rerender } = renderHook(() => useTestConnection());
    const firstRef = result.current.reset;

    // Act
    rerender();

    // Assert
    expect(result.current.reset).toBe(firstRef);
  });
});
