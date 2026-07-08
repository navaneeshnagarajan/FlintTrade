/**
 * useSettingsState tests
 *
 * Tests that the hook correctly reads from settingsStore + connectionStore
 * and exposes the right section data shapes.
 *
 * The websocket service is mocked so resetWsService doesn't blow up in jsdom.
 */

import { describe, it, expect, afterEach, beforeEach, vi } from "vitest";
import { act, renderHook, waitFor } from "@testing-library/react";
import { isAcceptedOpenAlgoConfigStatus, useSettingsState } from "../useSettingsState";
import { useSettingsStore } from "@/stores/settingsStore";
import { useConnectionStore } from "@/stores/connectionStore";

// ---------------------------------------------------------------------------
// Mock the websocket service (resetWsService would fail in jsdom)
// ---------------------------------------------------------------------------

vi.mock("@/services/websocket", () => ({
  resetWsService: vi.fn(),
}));

// Notification bus — failed connection saves must surface to the operator.
const mockEmitNotification = vi.hoisted(() => vi.fn());
vi.mock("@/components/NotificationCentre/useNotificationFeed", () => ({
  emitNotification: mockEmitNotification,
}));

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function resetStores() {
  useSettingsStore.setState(useSettingsStore.getInitialState());
  useConnectionStore.setState(useConnectionStore.getInitialState());
}

function mockFetchWithOpenAlgoConfig(
  config = { api_key_configured: false, api_key_last4: "", host: "", port: 5000, ws_port: 8765 },
  llmConfig = { provider: "", host: "", model: "", api_key_configured: false, api_key_last4: "" },
) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    if (init?.method === "POST") {
      return {
        ok: true,
        json: async () => ({ status: "ok" }),
      } as Response;
    }
    if (String(input).includes("/config/llm")) {
      return {
        ok: true,
        json: async () => ({ status: "success", data: llmConfig }),
      } as Response;
    }
    return {
      ok: true,
      json: async () => ({ status: "success", data: config }),
    } as Response;
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function mockFetchWithFailedPost(
  config = { api_key_configured: false, api_key_last4: "", host: "", port: 5000, ws_port: 8765 },
  llmConfig = { provider: "", host: "", model: "", api_key_configured: false, api_key_last4: "" },
) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    if (init?.method === "POST") {
      return {
        ok: false,
        status: 500,
        json: async () => ({ status: "error", message: "workspace locked" }),
      } as Response;
    }
    if (String(input).includes("/config/llm")) {
      return {
        ok: true,
        json: async () => ({ status: "success", data: llmConfig }),
      } as Response;
    }
    return {
      ok: true,
      json: async () => ({ status: "success", data: config }),
    } as Response;
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("useSettingsState", () => {
  beforeEach(() => {
    resetStores();
    mockFetchWithOpenAlgoConfig();
    mockEmitNotification.mockClear();
  });

  afterEach(() => {
    // LLM persistence is debounced with timers; a test that leaves fake timers
    // installed would poison the next one, so always restore real timers.
    vi.useRealTimers();
  });

  it("accepts backend OpenAlgo config save status variants", () => {
    expect(isAcceptedOpenAlgoConfigStatus("ok")).toBe(true);
    expect(isAcceptedOpenAlgoConfigStatus("success")).toBe(true);
    expect(isAcceptedOpenAlgoConfigStatus("partial")).toBe(true);
    expect(isAcceptedOpenAlgoConfigStatus("error")).toBe(false);
  });

  it("returns general with fontSize from settingsStore", () => {
    useSettingsStore.setState({ fontSize: "large" });

    const { result } = renderHook(() => useSettingsState());

    expect(result.current.general.fontSize).toBe("large");
  });

  it("returns trading defaults from settingsStore", () => {
    useSettingsStore.setState({
      defaultExchange: "BSE",
      defaultProduct: "CNC",
      defaultOrderType: "LIMIT",
      defaultQty: 5,
    });

    const { result } = renderHook(() => useSettingsState());

    expect(result.current.trading.exchange).toBe("BSE");
    expect(result.current.trading.product).toBe("CNC");
    expect(result.current.trading.orderType).toBe("LIMIT");
    expect(result.current.trading.quantity).toBe("5");
  });

  it("returns risk limits as string values for form inputs", () => {
    useSettingsStore.setState({
      riskLimits: {
        maxPositionLots: 10,
        mtmStoploss: 5000,
        mtmTarget: 10000,
        maxOrdersPerMinute: 30,
      },
    });

    const { result } = renderHook(() => useSettingsState());

    expect(result.current.risk.maxPositionLots).toBe("10");
    expect(result.current.risk.mtmStoploss).toBe("5000");
    expect(result.current.risk.mtmTarget).toBe("10000");
    expect(result.current.risk.maxOrdersPerMinute).toBe("30");
  });

  it("returns connection data from connectionStore", () => {
    useConnectionStore.setState({
      host: "http://192.168.1.10:5000",
      apiKey: "test-api-key",
      wsUrl: "ws://192.168.1.10:8765",
    });

    const { result } = renderHook(() => useSettingsState());

    expect(result.current.connection.host).toBe("http://192.168.1.10:5000");
    expect(result.current.connection.port).toBe("5000");
    expect(result.current.connection.apiKey).toBe("test-api-key");
    expect(result.current.connection.wsPort).toBe("8765");
  });

  it("hydrates connection data from the backend workspace endpoint", async () => {
    mockFetchWithOpenAlgoConfig({
      api_key_configured: true,
      api_key_last4: "-key",
      host: "http://192.168.1.20",
      port: 5001,
      ws_port: 8770,
    });

    const { result } = renderHook(() => useSettingsState());

    await waitFor(() => {
      expect(result.current.connection.host).toBe("http://192.168.1.20");
      expect(result.current.connection.port).toBe("5001");
      expect(result.current.connection.apiKey).toBe("");
      expect(result.current.connection.wsPort).toBe("8770");
    });
  });

  it("persists pre-hydration connection edits as partial backend patches", async () => {
    const fetchMock = mockFetchWithOpenAlgoConfig();
    const { result } = renderHook(() => useSettingsState());

    act(() => {
      result.current.updateConnection("host", "https://openalgo.local:5000");
    });

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        "/ft-api/v1/config/openalgo",
        expect.objectContaining({
          method: "POST",
          body: JSON.stringify({
            host: "https://openalgo.local:5000",
          }),
        }),
      );
    });
    expect(useConnectionStore.getState().wsUrl).toBe("wss://openalgo.local:8765");
  });

  it("persists REST port edits as partial backend patches", async () => {
    const fetchMock = mockFetchWithOpenAlgoConfig({
      api_key_configured: true,
      api_key_last4: "-key",
      host: "http://192.168.1.20",
      port: 5001,
      ws_port: 8770,
    });
    const { result } = renderHook(() => useSettingsState());

    await waitFor(() => {
      expect(result.current.connection.port).toBe("5001");
    });

    act(() => {
      result.current.updateConnection("port", "5010");
    });

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        "/ft-api/v1/config/openalgo",
        expect.objectContaining({
          method: "POST",
          body: JSON.stringify({
            port: "5010",
          }),
        }),
      );
      expect(result.current.connection.port).toBe("5010");
    });
  });

  it("treats a cleared REST port as clearing the override — never POSTs an empty port", async () => {
    // Backend contract (/v1/config/openalgo): port must be an int 1-65535 when
    // present, so {"port": ""} silently 400s (item 6). Clearing the field must
    // omit the key instead, and locally fall back to host-derived/default.
    const fetchMock = mockFetchWithOpenAlgoConfig({
      api_key_configured: true,
      api_key_last4: "-key",
      host: "http://192.168.1.20",
      port: 5001,
      ws_port: 8770,
    });
    const { result } = renderHook(() => useSettingsState());

    await waitFor(() => {
      expect(result.current.connection.port).toBe("5001");
    });
    const postCallsBefore = fetchMock.mock.calls.filter(
      (call) => (call[1] as RequestInit | undefined)?.method === "POST",
    ).length;

    act(() => {
      result.current.updateConnection("port", "");
    });
    act(() => {
      result.current.updateConnection("wsPort", "  ");
    });
    await act(async () => {
      await Promise.resolve();
    });

    const postCallsAfter = fetchMock.mock.calls.filter(
      (call) => (call[1] as RequestInit | undefined)?.method === "POST",
    );
    expect(postCallsAfter.length).toBe(postCallsBefore);
    // Local override cleared — the effective default is shown, not "".
    expect(result.current.connection.port).toBe("5000");
  });

  it("surfaces a failed connection save as a notification (item 6)", async () => {
    mockFetchWithFailedPost({
      api_key_configured: true,
      api_key_last4: "-key",
      host: "http://192.168.1.20:5000",
      port: 5000,
      ws_port: 8770,
    });
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    const { result } = renderHook(() => useSettingsState());

    await waitFor(() => {
      expect(result.current.connection.wsPort).toBe("8770");
    });

    act(() => {
      result.current.updateConnection("apiKey", "next-key");
    });

    await waitFor(() => {
      expect(mockEmitNotification).toHaveBeenCalledWith(
        expect.objectContaining({
          category: "system",
          title: "Connection settings not saved",
          body: "workspace locked",
        }),
      );
    });
    warnSpy.mockRestore();
  });

  it("merges late hydration data around a pre-hydration edit", async () => {
    let resolveGet: ((response: Response) => void) | undefined;
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      if (init?.method === "POST") {
        return Promise.resolve({
          ok: true,
          json: async () => ({ status: "ok" }),
        } as Response);
      }
      if (String(input).includes("/config/llm")) {
        return Promise.resolve({
          ok: true,
          json: async () => ({
            status: "success",
            data: {
              provider: "",
              host: "",
              model: "",
              api_key_configured: false,
              api_key_last4: "",
            },
          }),
        } as Response);
      }
      return new Promise<Response>((resolve) => {
        resolveGet = resolve;
      });
    });
    vi.stubGlobal("fetch", fetchMock);
    const { result } = renderHook(() => useSettingsState());

    act(() => {
      result.current.updateConnection("host", "https://openalgo.local:5000");
    });

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        "/ft-api/v1/config/openalgo",
        expect.objectContaining({
          method: "POST",
          body: JSON.stringify({
            host: "https://openalgo.local:5000",
          }),
        }),
      );
    });

    act(() => {
      resolveGet?.({
        ok: true,
        json: async () => ({
          status: "success",
          data: {
            api_key_configured: true,
            api_key_last4: "-key",
            host: "http://192.168.1.20:5000",
            port: 5001,
            ws_port: 8770,
          },
        }),
      } as Response);
    });

    await waitFor(() => {
      expect(result.current.connection.host).toBe("https://openalgo.local:5000");
      expect(result.current.connection.port).toBe("5000");
      expect(result.current.connection.apiKey).toBe("");
      expect(result.current.connection.wsPort).toBe("8770");
    });
    expect(useConnectionStore.getState().wsUrl).toBe("wss://openalgo.local:8770");
  });

  it("persists hydrated connection edits as partial backend patches", async () => {
    const fetchMock = mockFetchWithOpenAlgoConfig({
      api_key_configured: true,
      api_key_last4: "-key",
      host: "http://192.168.1.20:5000",
      port: 5000,
      ws_port: 8770,
    });
    const { result } = renderHook(() => useSettingsState());

    await waitFor(() => {
      expect(result.current.connection.wsPort).toBe("8770");
    });

    act(() => {
      result.current.updateConnection("host", "https://openalgo.local:5000");
    });

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        "/ft-api/v1/config/openalgo",
        expect.objectContaining({
          method: "POST",
          body: JSON.stringify({
            host: "https://openalgo.local:5000",
          }),
        }),
      );
    });
  });

  it("accepts the backend ok status without logging a persistence warning", async () => {
    let postJsonConsumed: (() => void) | undefined;
    const postJsonConsumedPromise = new Promise<void>((resolve) => {
      postJsonConsumed = resolve;
    });
    const fetchMock = vi.fn(async (_: RequestInfo | URL, init?: RequestInit) => {
      if (init?.method === "POST") {
        return {
          ok: true,
          json: async () => {
            postJsonConsumed?.();
            return { status: "ok" };
          },
        } as Response;
      }
      return {
        ok: true,
        json: async () => ({
          status: "success",
          data: {
            api_key_configured: false,
            api_key_last4: "",
            host: "http://192.168.1.20:5000",
            port: 5000,
            ws_port: 8770,
          },
        }),
      } as Response;
    });
    vi.stubGlobal("fetch", fetchMock);
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    const { result } = renderHook(() => useSettingsState());

    await waitFor(() => {
      expect(result.current.connection.wsPort).toBe("8770");
    });

    act(() => {
      result.current.updateConnection("host", "https://openalgo.local:5000");
    });

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        "/ft-api/v1/config/openalgo",
        expect.objectContaining({ method: "POST" }),
      );
    });
    await postJsonConsumedPromise;
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(warnSpy).not.toHaveBeenCalled();
    warnSpy.mockRestore();
  });

  it("logs failed backend persistence responses", async () => {
    const fetchMock = mockFetchWithFailedPost({
      api_key_configured: true,
      api_key_last4: "-key",
      host: "http://192.168.1.20:5000",
      port: 5000,
      ws_port: 8770,
    });
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    const { result } = renderHook(() => useSettingsState());

    await waitFor(() => {
      expect(result.current.connection.wsPort).toBe("8770");
    });

    act(() => {
      result.current.updateConnection("apiKey", "next-key");
    });

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        "/ft-api/v1/config/openalgo",
        expect.objectContaining({ method: "POST" }),
      );
      expect(fetchMock).toHaveBeenCalledWith(
        "/ft-api/v1/config/openalgo",
        expect.objectContaining({
          method: "POST",
          body: JSON.stringify({
            api_key: "next-key",
          }),
        }),
      );
      expect(warnSpy).toHaveBeenCalledWith(
        "[settings] failed to persist OpenAlgo config:",
        expect.any(Error),
      );
    });
    warnSpy.mockRestore();
  });

  it("returns telegram settings from settingsStore", () => {
    useSettingsStore.setState({
      telegram: { enabled: true, botToken: "bot:token", chatId: "-100123" },
    });

    const { result } = renderHook(() => useSettingsState());

    expect(result.current.telegram.enabled).toBe(true);
    expect(result.current.telegram.botToken).toBe("bot:token");
    expect(result.current.telegram.chatId).toBe("-100123");
  });

  it("returns dataPaths from settingsStore", () => {
    useSettingsStore.setState({
      dataPaths: { fastStoragePath: "/ssd/data", archiveStoragePath: "/hdd/archive" },
    });

    const { result } = renderHook(() => useSettingsState());

    expect(result.current.dataPaths.fastStoragePath).toBe("/ssd/data");
    expect(result.current.dataPaths.archiveStoragePath).toBe("/hdd/archive");
  });

  it("returns llm data from settingsStore with lmstudio default provider", () => {
    // With empty provider, hook defaults to "lmstudio"
    useSettingsStore.setState({
      llm: { provider: "", model: "qwen3:9b", host: "http://127.0.0.1:1234", apiKey: "" },
    });

    const { result } = renderHook(() => useSettingsState());

    expect(result.current.llm.provider).toBe("lmstudio");
    expect(result.current.llm.model).toBe("qwen3:9b");
  });

  it("hydrates LLM config from the backend workspace endpoint without exposing the API key", async () => {
    mockFetchWithOpenAlgoConfig(undefined, {
      provider: "openai",
      host: "",
      model: "gpt-4o",
      api_key_configured: true,
      api_key_last4: "test",
    });

    const { result } = renderHook(() => useSettingsState());

    await waitFor(() => {
      expect(result.current.llm.provider).toBe("openai");
      expect(result.current.llm.model).toBe("gpt-4o");
      expect(result.current.llm.apiKey).toBe("");
    });
  });

  function postCalls(fetchMock: ReturnType<typeof mockFetchWithOpenAlgoConfig>) {
    return fetchMock.mock.calls.filter(
      (call) => (call[1] as RequestInit | undefined)?.method === "POST",
    );
  }

  it("persists LLM edits as a debounced partial backend patch", async () => {
    vi.useFakeTimers();
    const fetchMock = mockFetchWithOpenAlgoConfig();
    const { result } = renderHook(() => useSettingsState());

    act(() => {
      result.current.updateLLM("apiKey", "sk-next-key");
    });
    // Inside the debounce window nothing is persisted yet.
    expect(postCalls(fetchMock)).toHaveLength(0);

    act(() => {
      vi.advanceTimersByTime(1000);
    });
    vi.useRealTimers();

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        "/ft-api/v1/config/llm",
        expect.objectContaining({
          method: "POST",
          body: JSON.stringify({ api_key: "sk-next-key" }),
        }),
      );
    });
  });

  it("does not persist LLM config per keystroke — coalesces rapid edits into one POST", async () => {
    // POST /v1/config/llm is rate limited to 10/min, and a per-keystroke save
    // can leave a truncated key as the last value written to the secret file.
    vi.useFakeTimers();
    const fetchMock = mockFetchWithOpenAlgoConfig();
    const { result } = renderHook(() => useSettingsState());

    act(() => {
      result.current.updateLLM("apiKey", "s");
      result.current.updateLLM("apiKey", "sk");
      result.current.updateLLM("apiKey", "sk-live-1234");
    });
    // Still mid-type — no partial key persisted.
    expect(postCalls(fetchMock)).toHaveLength(0);

    act(() => {
      vi.advanceTimersByTime(1000);
    });
    vi.useRealTimers();

    await waitFor(() => {
      const posts = postCalls(fetchMock);
      expect(posts).toHaveLength(1);
      expect(posts[0][0]).toBe("/ft-api/v1/config/llm");
      expect((posts[0][1] as RequestInit).body).toBe(JSON.stringify({ api_key: "sk-live-1234" }));
    });
  });

  it("coalesces edits across LLM fields into a single debounced POST", async () => {
    vi.useFakeTimers();
    const fetchMock = mockFetchWithOpenAlgoConfig();
    const { result } = renderHook(() => useSettingsState());

    act(() => {
      result.current.updateLLM("provider", "openai");
      result.current.updateLLM("model", "gpt-4o");
      result.current.updateLLM("apiKey", "sk-key");
    });

    act(() => {
      vi.advanceTimersByTime(1000);
    });
    vi.useRealTimers();

    await waitFor(() => {
      const posts = postCalls(fetchMock);
      expect(posts).toHaveLength(1);
      expect((posts[0][1] as RequestInit).body).toBe(
        JSON.stringify({ provider: "openai", model: "gpt-4o", api_key: "sk-key" }),
      );
    });
  });

  it("surfaces a failed LLM save as a notification (never silently dropped)", async () => {
    vi.useFakeTimers();
    mockFetchWithFailedPost();
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    const { result } = renderHook(() => useSettingsState());

    act(() => {
      result.current.updateLLM("apiKey", "sk-bad-key");
    });
    act(() => {
      vi.advanceTimersByTime(1000);
    });
    vi.useRealTimers();

    await waitFor(() => {
      expect(mockEmitNotification).toHaveBeenCalledWith(
        expect.objectContaining({
          category: "system",
          title: "LLM settings not saved",
          body: "workspace locked",
        }),
      );
    });
    warnSpy.mockRestore();
  });

  it("flushes a pending LLM edit when the settings surface unmounts", async () => {
    vi.useFakeTimers();
    const fetchMock = mockFetchWithOpenAlgoConfig();
    const { result, unmount } = renderHook(() => useSettingsState());

    act(() => {
      result.current.updateLLM("model", "gpt-4o");
    });
    // Inside the debounce window — not yet persisted.
    expect(postCalls(fetchMock)).toHaveLength(0);

    act(() => {
      unmount();
    });
    vi.useRealTimers();

    await waitFor(() => {
      const posts = postCalls(fetchMock);
      expect(posts).toHaveLength(1);
      expect((posts[0][1] as RequestInit).body).toBe(JSON.stringify({ model: "gpt-4o" }));
    });
  });

  it("exposes update action functions", () => {
    const { result } = renderHook(() => useSettingsState());

    expect(typeof result.current.updateGeneral).toBe("function");
    expect(typeof result.current.updateTradingDefaults).toBe("function");
    expect(typeof result.current.updateRiskLimits).toBe("function");
    expect(typeof result.current.updateLLM).toBe("function");
    expect(typeof result.current.updateTelegram).toBe("function");
    expect(typeof result.current.updateDataPaths).toBe("function");
    expect(typeof result.current.updateConnection).toBe("function");
    expect(typeof result.current.handleRestart).toBe("function");
  });

  it("restarting is false by default", () => {
    const { result } = renderHook(() => useSettingsState());
    expect(result.current.restarting).toBe(false);
  });

  it("preserves zero risk values as '0' (not empty string)", () => {
    // 0 is a valid limit value — the hook must not coerce it to "" via falsy check.
    useSettingsStore.setState({
      riskLimits: {
        maxPositionLots: 0,
        mtmStoploss: 0,
        mtmTarget: 0,
        maxOrdersPerMinute: 0,
      },
    });

    const { result } = renderHook(() => useSettingsState());

    expect(result.current.risk.maxPositionLots).toBe("0");
    expect(result.current.risk.mtmStoploss).toBe("0");
    expect(result.current.risk.mtmTarget).toBe("0");
    expect(result.current.risk.maxOrdersPerMinute).toBe("0");
  });
});
