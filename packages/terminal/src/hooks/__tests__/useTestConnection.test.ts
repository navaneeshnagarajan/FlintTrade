/**
 * useTestConnection.test.ts
 *
 * Tests for the useTestConnection hook.
 *
 * The hook posts `{host, api_key}` to `/ft-api/v1/test-connection` on the
 * FlintTrade backend. The backend performs the real OpenAlgo ping server-
 * to-server and returns a JSON envelope of the form
 *     { status: "ok" | "error", message: string, ... }
 * wrapped in an HTTP 200 (so we always get structured info — even failures).
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
const BACKEND_URL = "/ft-api/v1/test-connection";

/**
 * Build a Response-like object that the hook's `await response.json()` call
 * can consume. HTTP status always 200 here by default because the backend
 * wraps failures in structured JSON — pass a different `status` only when
 * testing the HTTP-level error path (500 etc.).
 */
function makeResponse(
  body: Record<string, unknown>,
  opts: { status?: number; ok?: boolean } = {},
): Response {
  const status = opts.status ?? 200;
  const ok = opts.ok ?? (status >= 200 && status < 300);
  return {
    ok,
    status,
    json: async () => body,
  } as unknown as Response;
}

/** Build a response that looks like the backend's "auth failed" 200 envelope. */
function makeErrorEnvelope(message: string, httpStatus = 200): Response {
  return makeResponse({ status: "error", message }, { status: httpStatus });
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
// Successful connection (backend returns {status: "ok"})
// ---------------------------------------------------------------------------

describe("useTestConnection — successful connection", () => {
  it("sets status to 'ok' when the backend responds with status=ok", async () => {
    // Arrange
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        makeResponse({ status: "ok", message: "Connected — broker: dhan" }),
      ),
    );
    const { result } = renderHook(() => useTestConnection());

    // Act
    await act(async () => {
      await result.current.testConnection(HOST, API_KEY);
    });

    // Assert
    expect(result.current.status).toBe<TestConnectionStatus>("ok");
  });

  it("uses the backend's message verbatim when available", async () => {
    // Arrange
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        makeResponse({ status: "ok", message: "Connected — broker: dhan" }),
      ),
    );
    const { result } = renderHook(() => useTestConnection());

    // Act
    await act(async () => {
      await result.current.testConnection(HOST, API_KEY);
    });

    // Assert
    expect(result.current.message).toBe("Connected — broker: dhan");
  });

  it("falls back to 'Connected successfully' when backend omits the message", async () => {
    // Arrange — status=ok but no message field
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(makeResponse({ status: "ok" })),
    );
    const { result } = renderHook(() => useTestConnection());

    // Act
    await act(async () => {
      await result.current.testConnection(HOST, API_KEY);
    });

    // Assert
    expect(result.current.message).toBe("Connected successfully");
  });

  it("POSTs to the FlintTrade backend endpoint (not OpenAlgo directly)", async () => {
    // Arrange
    const mockFetch = vi.fn().mockResolvedValue(makeResponse({ status: "ok" }));
    vi.stubGlobal("fetch", mockFetch);
    const { result } = renderHook(() => useTestConnection());

    // Act
    await act(async () => {
      await result.current.testConnection(HOST, API_KEY);
    });

    // Assert — the browser cannot hit OpenAlgo directly (CORS), so the hook
    // must route through the backend proxy.
    expect(mockFetch).toHaveBeenCalledOnce();
    const [url, options] = mockFetch.mock.calls[0] as [string, RequestInit];
    expect(url).toBe(BACKEND_URL);
    expect(options.method).toBe("POST");
  });

  it("sends host and api_key in the request body", async () => {
    // Arrange
    const mockFetch = vi.fn().mockResolvedValue(makeResponse({ status: "ok" }));
    vi.stubGlobal("fetch", mockFetch);
    const { result } = renderHook(() => useTestConnection());

    // Act
    await act(async () => {
      await result.current.testConnection(HOST, API_KEY);
    });

    // Assert — the backend expects `{host, api_key}`, NOT `{apikey}`.
    const [, options] = mockFetch.mock.calls[0] as [string, RequestInit];
    const body = JSON.parse(options.body as string) as Record<string, string>;
    expect(body.host).toBe(HOST);
    expect(body.api_key).toBe(API_KEY);
  });

  it("strips trailing slashes from the host before sending", async () => {
    // Arrange
    const mockFetch = vi.fn().mockResolvedValue(makeResponse({ status: "ok" }));
    vi.stubGlobal("fetch", mockFetch);
    const { result } = renderHook(() => useTestConnection());

    // Act — host with one or more trailing slashes should be normalised.
    await act(async () => {
      await result.current.testConnection("http://localhost:5000//", API_KEY);
    });

    // Assert
    const [, options] = mockFetch.mock.calls[0] as [string, RequestInit];
    const body = JSON.parse(options.body as string) as Record<string, string>;
    expect(body.host).toBe("http://localhost:5000");
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
      resolveRequest(makeResponse({ status: "ok" }));
      await pendingRequest;
    });
  });

  it("clears the previous message when a new test starts", async () => {
    // Arrange — first call fails, second call succeeds
    const mockFetch = vi
      .fn()
      .mockResolvedValueOnce(makeErrorEnvelope("Invalid API key"))
      .mockResolvedValueOnce(makeResponse({ status: "ok" }));
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
      resolveSecond(makeResponse({ status: "ok" }));
      await secondRequest;
    });
  });
});

// ---------------------------------------------------------------------------
// Backend-reported errors (HTTP 200 + status=error envelope)
// ---------------------------------------------------------------------------

describe("useTestConnection — backend error envelope", () => {
  it("sets status to 'error' when the backend reports an auth failure", async () => {
    // Arrange — HTTP 200 but structured auth-failed body (our standard shape)
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        makeErrorEnvelope("Reachable but auth failed (HTTP 401): Invalid API key"),
      ),
    );
    const { result } = renderHook(() => useTestConnection());

    // Act
    await act(async () => {
      await result.current.testConnection(HOST, "bad-key");
    });

    // Assert
    expect(result.current.status).toBe<TestConnectionStatus>("error");
    expect(result.current.message).toContain("auth failed");
  });

  it("surfaces the backend's message when unreachable", async () => {
    // Arrange
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        makeErrorEnvelope("Cannot reach OpenAlgo at http://localhost:5000"),
      ),
    );
    const { result } = renderHook(() => useTestConnection());

    // Act
    await act(async () => {
      await result.current.testConnection(HOST, API_KEY);
    });

    // Assert
    expect(result.current.status).toBe<TestConnectionStatus>("error");
    expect(result.current.message).toContain("Cannot reach OpenAlgo");
  });
});

// ---------------------------------------------------------------------------
// Error cases — HTTP-level (backend itself misbehaves)
// ---------------------------------------------------------------------------

describe("useTestConnection — HTTP error responses", () => {
  it("sets status to 'error' when the backend returns 500", async () => {
    // Arrange — backend itself is broken (not an OpenAlgo error)
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        makeResponse(
          { status: "error", message: "Internal server error" },
          { status: 500, ok: false },
        ),
      ),
    );
    const { result } = renderHook(() => useTestConnection());

    // Act
    await act(async () => {
      await result.current.testConnection(HOST, API_KEY);
    });

    // Assert
    expect(result.current.status).toBe<TestConnectionStatus>("error");
    expect(result.current.message).toContain("Internal server error");
  });

  it("includes the HTTP status in the message when the backend returns 400 with no body message", async () => {
    // Arrange — backend returned non-2xx but no structured message
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        makeResponse({}, { status: 400, ok: false }),
      ),
    );
    const { result } = renderHook(() => useTestConnection());

    // Act
    await act(async () => {
      await result.current.testConnection(HOST, API_KEY);
    });

    // Assert — hook falls back to "Server returned 400"
    expect(result.current.status).toBe<TestConnectionStatus>("error");
    expect(result.current.message).toContain("400");
  });

  it("handles an invalid-JSON body gracefully", async () => {
    // Arrange — response.json() throws (backend returned HTML, for example)
    const bad = {
      ok: true,
      status: 200,
      json: async () => {
        throw new Error("Unexpected token < in JSON at position 0");
      },
    } as unknown as Response;
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(bad));
    const { result } = renderHook(() => useTestConnection());

    // Act
    await act(async () => {
      await result.current.testConnection(HOST, API_KEY);
    });

    // Assert — hook catches the parse failure and reports the fallback
    expect(result.current.status).toBe<TestConnectionStatus>("error");
    expect(result.current.message).toContain("Invalid JSON");
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
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(makeResponse({ status: "ok" })),
    );
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
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(makeResponse({ status: "ok" })),
    );
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
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(makeResponse({ status: "ok" })),
    );
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
