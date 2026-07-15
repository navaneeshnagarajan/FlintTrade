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
import type { OpenAlgoConfigData } from "@/services/ftApi.openalgo";

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

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((nextResolve, nextReject) => {
    resolve = nextResolve;
    reject = nextReject;
  });
  return { promise, resolve, reject };
}

function mockFetchWithOpenAlgoConfig(
  config: OpenAlgoConfigData = {
    api_key_configured: false,
    api_key_last4: "",
    host: "",
    port: 5000,
    ws_port: 8765,
  },
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

  it("returns redacted connection data from the memory-only connection cache", async () => {
    mockFetchWithOpenAlgoConfig({
      api_key: "test-api-key",
      api_key_configured: true,
      api_key_last4: "-key",
      host: "http://192.168.1.10:5000",
      port: 5000,
      ws_port: 8765,
    });

    const { result } = renderHook(() => useSettingsState());

    await waitFor(() => {
      expect(result.current.connection).toEqual({
        host: "http://192.168.1.10:5000",
        port: "5000",
        wsPort: "8765",
        apiKeyConfigured: true,
        apiKeyLast4: "-key",
      });
    });
    expect(result.current.connection).not.toHaveProperty("apiKey");
    expect(useConnectionStore.getState().apiKey).toBe("test-api-key");
  });

  it("hydrates connection metadata and the memory-only runtime key from the workspace endpoint", async () => {
    mockFetchWithOpenAlgoConfig({
      api_key: "workspace-api-key",
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
      expect(result.current.connection.wsPort).toBe("8770");
      expect(result.current.connection.apiKeyConfigured).toBe(true);
      expect(result.current.connection.apiKeyLast4).toBe("-key");
    });
    expect(useConnectionStore.getState().apiKey).toBe("workspace-api-key");
  });

  it("accepts an explicitly saved connection without issuing another backend write", async () => {
    const fetchMock = mockFetchWithOpenAlgoConfig({
      api_key: "existing-api-key",
      api_key_configured: true,
      api_key_last4: "-key",
      host: "http://127.0.0.1:5000",
      port: 5000,
      ws_port: 8765,
    });
    const { result } = renderHook(() => useSettingsState());

    await waitFor(() => {
      expect(result.current.connection.apiKeyConfigured).toBe(true);
    });

    act(() => {
      useConnectionStore.getState().setConfig({
        host: "https://openalgo.local",
        apiKey: "replacement-api-key",
        wsUrl: "wss://openalgo.local:9770",
      });
      result.current.acceptConnection({
        host: "https://openalgo.local",
        port: "5010",
        apiKey: "replacement-api-key",
        wsPort: "9770",
      });
    });

    expect(result.current.connection).toEqual({
      host: "https://openalgo.local",
      port: "5010",
      wsPort: "9770",
      apiKeyConfigured: true,
      apiKeyLast4: "-key",
    });
    expect(fetchMock.mock.calls.filter(
      (call) => (call[1] as RequestInit | undefined)?.method === "POST",
    )).toHaveLength(0);
  });

  it("keeps saved credential metadata when an accepted save omits a replacement key", async () => {
    mockFetchWithOpenAlgoConfig({
      api_key: "existing-api-key",
      api_key_configured: true,
      api_key_last4: "-key",
      host: "http://127.0.0.1:5000",
      port: 5000,
      ws_port: 8765,
    });
    const { result } = renderHook(() => useSettingsState());

    await waitFor(() => {
      expect(useConnectionStore.getState().apiKey).toBe("existing-api-key");
    });

    act(() => {
      result.current.acceptConnection({
        host: "http://127.0.0.1:5000",
        port: "5000",
        apiKey: "",
        wsPort: "8765",
      });
    });

    expect(result.current.connection.apiKeyConfigured).toBe(true);
    expect(result.current.connection.apiKeyLast4).toBe("-key");
  });

  it("does not let an older hydration response overwrite an accepted save", async () => {
    let resolveOpenAlgo: ((response: Response) => void) | undefined;
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => {
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
        resolveOpenAlgo = resolve;
      });
    }));
    const { result } = renderHook(() => useSettingsState());

    act(() => {
      useConnectionStore.getState().setConfig({
        host: "https://new-openalgo.local",
        apiKey: "new-api-key",
        wsUrl: "wss://new-openalgo.local:9770",
      });
      result.current.acceptConnection({
        host: "https://new-openalgo.local",
        port: "5010",
        apiKey: "new-api-key",
        wsPort: "9770",
      });
    });

    await act(async () => {
      resolveOpenAlgo?.({
        ok: true,
        json: async () => ({
          status: "success",
          data: {
            api_key: "old-api-key",
            api_key_configured: true,
            api_key_last4: "-key",
            host: "http://old-openalgo.local:5000",
            port: 5000,
            ws_port: 8765,
          },
        }),
      } as Response);
      await Promise.resolve();
    });

    expect(result.current.connection).toEqual({
      host: "https://new-openalgo.local",
      port: "5010",
      wsPort: "9770",
      apiKeyConfigured: true,
      apiKeyLast4: "-key",
    });
    expect(useConnectionStore.getState().apiKey).toBe("new-api-key");
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

  it("returns llm data from settingsStore with managed Ollama as the default provider", () => {
    useSettingsStore.setState({
      llm: { provider: "", authMode: "api-key", model: "qwen3:9b", host: "", apiKey: "" },
    });

    const { result } = renderHook(() => useSettingsState());

    expect(result.current.llm.provider).toBe("ollama");
    expect(result.current.llm.host).toBe("");
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
      expect(result.current.llmCredentialConfigured).toBe(true);
      expect(result.current.llmCredentialLast4).toBe("test");
    });
  });

  it("blocks LLM edits until authoritative hydration completes", async () => {
    const llmRead = deferred<Response>();
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      if (init?.method === "POST") {
        return new Response(JSON.stringify({ status: "success", data: {} }));
      }
      if (String(input).includes("/config/llm")) return llmRead.promise;
      return new Response(JSON.stringify({ status: "success", data: {} }));
    });
    vi.stubGlobal("fetch", fetchMock);
    useSettingsStore.setState({
      llm: { provider: "openai", authMode: "api-key", host: "", model: "gpt-4o", apiKey: "" },
    });

    const { result } = renderHook(() => useSettingsState());

    act(() => {
      result.current.updateLLM("model", "stale-local-model");
      result.current.updateLLM("apiKey", "must-not-leave-the-browser");
    });
    expect(result.current.llm.model).toBe("gpt-4o");
    expect(result.current.llm.apiKey).toBe("");
    expect(postCalls(fetchMock)).toHaveLength(0);

    await act(async () => {
      llmRead.resolve(new Response(JSON.stringify({
        status: "success",
        data: {
          provider: "anthropic",
          host: "",
          model: "claude-3-5-haiku-20241022",
          api_key_configured: true,
          api_key_last4: "last",
        },
      })));
      await llmRead.promise;
    });

    await waitFor(() => expect(result.current.llm.provider).toBe("anthropic"));
    expect(result.current.llm.model).toBe("claude-3-5-haiku-20241022");
    expect(result.current.llm.apiKey).toBe("");
    expect(postCalls(fetchMock)).toHaveLength(0);
  });

  it("keeps a managed Ollama endpoint returned by the backend backend-only", async () => {
    mockFetchWithOpenAlgoConfig(undefined, {
      provider: "ollama",
      host: "http://127.0.0.1:49157",
      model: "qwen3:8b",
      api_key_configured: false,
      api_key_last4: "",
    });

    const { result } = renderHook(() => useSettingsState());

    await waitFor(() => {
      expect(result.current.llm.provider).toBe("ollama");
      expect(result.current.llm.host).toBe("");
      expect(useSettingsStore.getState().llm.host).toBe("");
    });
  });

  it("preserves a setup draft through hydration and clears it after authenticated activation", async () => {
    useSettingsStore.setState({
      llm: { provider: "grok", authMode: "api-key", host: "", model: "grok-3-mini", apiKey: "" },
      llmSetupPending: true,
    });
    const fetchMock = mockFetchWithOpenAlgoConfig(undefined, {
      provider: "openai",
      host: "",
      model: "gpt-4o",
      api_key_configured: true,
      api_key_last4: "last",
    });
    const { result } = renderHook(() => useSettingsState());

    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      "/ft-api/v1/config/llm",
      expect.anything(),
    ));
    expect(result.current.llm.provider).toBe("grok");
    expect(result.current.llm.model).toBe("grok-3-mini");
    expect(result.current.llmSetupPending).toBe(true);

    await act(async () => {
      await result.current.updateLLMProvider("grok", "", "grok-3-mini", "xai-secret");
    });

    expect(result.current.llmSetupPending).toBe(false);
    expect((postCalls(fetchMock)[0][1] as RequestInit).body).toBe(JSON.stringify({
      provider: "grok",
      host: "",
      model: "grok-3-mini",
      api_key: "xai-secret",
    }));
  });

  it("keeps a setup provider draft and retry state when authenticated activation fails", async () => {
    useSettingsStore.setState({
      llm: { provider: "grok", authMode: "api-key", host: "", model: "grok-3-mini", apiKey: "" },
      llmSetupPending: true,
    });
    const fetchMock = mockFetchWithFailedPost(undefined, {
      provider: "openai",
      host: "",
      model: "gpt-4o",
      api_key_configured: true,
      api_key_last4: "last",
    });
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    const { result } = renderHook(() => useSettingsState());

    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      "/ft-api/v1/config/llm",
      expect.anything(),
    ));

    await act(async () => {
      await expect(
        result.current.updateLLMProvider("grok", "", "grok-3-mini", "xai-secret"),
      ).rejects.toThrow("workspace locked");
    });

    expect(result.current.llmSetupPending).toBe(true);
    expect(result.current.llm).toEqual(expect.objectContaining({
      provider: "grok",
      model: "grok-3-mini",
    }));
    expect(result.current.llmSaveState).toBe("error");
    warnSpy.mockRestore();
  });

  it("commits managed provider and empty logical host atomically before updating local state", async () => {
    const save = deferred<Response>();
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      if (init?.method === "POST" && String(input).includes("/config/llm")) {
        return save.promise;
      }
      if (String(input).includes("/config/llm")) {
        return new Response(JSON.stringify({
          status: "success",
          data: { provider: "openai", host: "", model: "gpt-4o" },
        }));
      }
      return new Response(JSON.stringify({ status: "success", data: {} }));
    });
    vi.stubGlobal("fetch", fetchMock);
    const { result } = renderHook(() => useSettingsState());

    await waitFor(() => expect(result.current.llm.provider).toBe("openai"));

    let providerUpdate!: Promise<void>;
    act(() => {
      providerUpdate = result.current.updateLLMProvider("ollama");
    });

    await waitFor(() => expect(postCalls(fetchMock)).toHaveLength(1));
    expect((postCalls(fetchMock)[0][1] as RequestInit).body).toBe(JSON.stringify({
      provider: "ollama",
      host: "",
      model: "qwen3:8b",
    }));
    expect(result.current.llm.provider).toBe("openai");

    await act(async () => {
      save.resolve(new Response(JSON.stringify({
        status: "success",
        data: { provider: "ollama", host: "http://127.0.0.1:49157", model: "gpt-4o" },
      })));
      await providerUpdate;
    });

    expect(result.current.llm.provider).toBe("ollama");
    expect(result.current.llm.host).toBe("");
  });

  it("restores authoritative backend state when a provider transaction fails", async () => {
    let llmReads = 0;
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      if (init?.method === "POST" && String(input).includes("/config/llm")) {
        return new Response(
          JSON.stringify({ status: "error", message: "workspace locked" }),
          { status: 500 },
        );
      }
      if (String(input).includes("/config/llm")) {
        llmReads += 1;
        const data = llmReads === 1
          ? { provider: "openai", host: "", model: "gpt-4o" }
          : { provider: "anthropic", host: "", model: "claude-3-5-haiku" };
        return new Response(JSON.stringify({ status: "success", data }));
      }
      return new Response(JSON.stringify({ status: "success", data: {} }));
    });
    vi.stubGlobal("fetch", fetchMock);
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    const { result } = renderHook(() => useSettingsState());

    await waitFor(() => expect(result.current.llm.provider).toBe("openai"));

    await act(async () => {
      await expect(result.current.updateLLMProvider("ollama")).rejects.toThrow("workspace locked");
    });

    expect(result.current.llm.provider).toBe("anthropic");
    expect(result.current.llm.model).toBe("claude-3-5-haiku");
    expect(mockEmitNotification).toHaveBeenCalledWith(expect.objectContaining({
      title: "LLM settings not saved",
      body: "workspace locked",
    }));
    warnSpy.mockRestore();
  });

  it("clears cloud hosts and rejects blank hosts for host-based providers", async () => {
    const fetchMock = mockFetchWithOpenAlgoConfig(undefined, {
      provider: "hermes",
      host: "http://hermes.internal:8000",
      model: "hermes-3",
      api_key_configured: false,
      api_key_last4: "",
    });
    const { result } = renderHook(() => useSettingsState());

    await waitFor(() => expect(result.current.llm.provider).toBe("hermes"));

    await act(async () => {
      await result.current.updateLLMProvider("openai", "", undefined, "sk-openai");
    });
    expect((postCalls(fetchMock)[0][1] as RequestInit).body).toBe(JSON.stringify({
      provider: "openai",
      host: "",
      model: "gpt-4o-mini",
      api_key: "sk-openai",
    }));
    expect(result.current.llm.host).toBe("");

    await act(async () => {
      await expect(result.current.updateLLMProvider("custom", "   "))
        .rejects.toThrow("Host URL is required for Custom Endpoint");
    });
    expect(postCalls(fetchMock)).toHaveLength(1);
  });

  it("does not accept a generic blank host edit for a credentialled provider", async () => {
    vi.useFakeTimers();
    const fetchMock = mockFetchWithOpenAlgoConfig(undefined, {
      provider: "custom",
      host: "http://127.0.0.1:9000",
      model: "private-model",
      api_key_configured: true,
      api_key_last4: "last",
    });
    const { result } = renderHook(() => useSettingsState());
    await vi.waitFor(() => expect(result.current.llm.provider).toBe("custom"));

    act(() => {
      result.current.updateLLM("host", "   ");
      vi.advanceTimersByTime(1000);
    });

    expect(result.current.llm.host).toBe("http://127.0.0.1:9000");
    expect(result.current.llmSaveState).toBe("saved");
    expect(postCalls(fetchMock)).toHaveLength(0);
  });

  it("requires a full credential transaction before changing a Custom trust destination", async () => {
    vi.useFakeTimers();
    const fetchMock = mockFetchWithOpenAlgoConfig(undefined, {
      provider: "custom",
      host: "https://old.example.test/v1",
      model: "private-model",
      api_key_configured: true,
      api_key_last4: "last",
    });
    const { result } = renderHook(() => useSettingsState());
    await vi.waitFor(() => expect(result.current.llm.provider).toBe("custom"));

    act(() => {
      result.current.updateLLM("apiKey", "old-secret");
      result.current.updateLLM("host", "https://new.example.test/v1");
      vi.advanceTimersByTime(1000);
    });
    expect(postCalls(fetchMock)).toHaveLength(0);
    expect(result.current.llm.host).toBe("https://old.example.test/v1");
    expect(result.current.llm.apiKey).toBe("");
    vi.useRealTimers();
  });

  it("persists a replacement provider credential in the same activation transaction", async () => {
    const fetchMock = mockFetchWithOpenAlgoConfig(undefined, {
      provider: "openai",
      host: "",
      model: "gpt-4o",
      api_key_configured: true,
      api_key_last4: "open",
    });
    const { result } = renderHook(() => useSettingsState());
    await waitFor(() => expect(result.current.llm.provider).toBe("openai"));

    await act(async () => {
      await result.current.updateLLMProvider(
        "anthropic",
        "",
        "claude-3-5-haiku",
        "sk-ant-replacement",
      );
    });

    expect(postCalls(fetchMock)).toHaveLength(1);
    expect((postCalls(fetchMock)[0][1] as RequestInit).body).toBe(JSON.stringify({
      provider: "anthropic",
      host: "",
      model: "claude-3-5-haiku",
      api_key: "sk-ant-replacement",
    }));
  });

  it("persists Claude Code OAuth as an auth marker without inventing a backend provider", async () => {
    const fetchMock = mockFetchWithOpenAlgoConfig(undefined, {
      provider: "openai",
      host: "",
      model: "gpt-4o-mini",
      api_key_configured: true,
      api_key_last4: "live",
    });
    const { result } = renderHook(() => useSettingsState());
    await waitFor(() => expect(result.current.llm.provider).toBe("openai"));

    await act(async () => {
      await result.current.updateLLMProvider(
        "anthropic",
        "",
        "claude-3-5-haiku-20241022",
        "oauth-credential",
        "claude-code-oauth",
      );
    });

    expect((postCalls(fetchMock)[0][1] as RequestInit).body).toBe(JSON.stringify({
      provider: "anthropic",
      host: "",
      model: "claude-3-5-haiku-20241022",
      api_key: "oauth-credential",
    }));
    expect(result.current.llm.provider).toBe("anthropic");
    expect(result.current.llm.authMode).toBe("claude-code-oauth");
  });

  it("removes a credential with a coherent full-provider transaction", async () => {
    const fetchMock = mockFetchWithOpenAlgoConfig(undefined, {
      provider: "openai",
      host: "",
      model: "gpt-4o-mini",
      api_key_configured: true,
      api_key_last4: "live",
    });
    const { result } = renderHook(() => useSettingsState());
    await waitFor(() => expect(result.current.llmCredentialConfigured).toBe(true));

    await act(async () => {
      await result.current.removeLLMCredential();
    });

    expect((postCalls(fetchMock)[0][1] as RequestInit).body).toBe(JSON.stringify({
      provider: "openai",
      host: "",
      model: "gpt-4o-mini",
      api_key: "",
    }));
    expect(result.current.llmCredentialConfigured).toBe(false);
    expect(result.current.llmCredentialLast4).toBe("");
  });

  it("ignores a generic secret edit before an explicit provider credential transaction", async () => {
    const providerSave = deferred<Response>();
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      if (init?.method === "POST" && String(input).includes("/config/llm")) {
        return providerSave.promise;
      }
      if (String(input).includes("/config/llm")) {
        return new Response(JSON.stringify({
          status: "success",
          data: { provider: "openai", host: "", model: "gpt-4o" },
        }));
      }
      return new Response(JSON.stringify({ status: "success", data: {} }));
    });
    vi.stubGlobal("fetch", fetchMock);
    const { result } = renderHook(() => useSettingsState());

    await vi.waitFor(() => expect(result.current.llm.provider).toBe("openai"));
    act(() => result.current.updateLLM("apiKey", "sk-openai"));
    expect(postCalls(fetchMock)).toHaveLength(0);

    let providerUpdate!: Promise<void>;
    act(() => {
      providerUpdate = result.current.updateLLMProvider("anthropic", "", undefined, "sk-anthropic");
    });

    await vi.waitFor(() => expect(postCalls(fetchMock)).toHaveLength(1));
    expect((postCalls(fetchMock)[0][1] as RequestInit).body).toBe(JSON.stringify({
      provider: "anthropic",
      host: "",
      model: "claude-3-5-haiku-20241022",
      api_key: "sk-anthropic",
    }));

    await act(async () => {
      providerSave.resolve(new Response(JSON.stringify({
        status: "success",
        data: { provider: "anthropic", host: "", model: "claude-3-5-haiku-20241022" },
      })));
      await providerUpdate;
    });
    expect(result.current.llm.provider).toBe("anthropic");
  });

  it("does not queue an old-provider secret while a provider transaction is in flight", async () => {
    vi.useFakeTimers();
    const providerSave = deferred<Response>();
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      if (init?.method === "POST" && String(input).includes("/config/llm")) {
        return providerSave.promise;
      }
      if (String(input).includes("/config/llm")) {
        return new Response(JSON.stringify({
          status: "success",
          data: { provider: "openai", host: "", model: "gpt-4o" },
        }));
      }
      return new Response(JSON.stringify({ status: "success", data: {} }));
    });
    vi.stubGlobal("fetch", fetchMock);
    const { result } = renderHook(() => useSettingsState());
    await vi.waitFor(() => expect(result.current.llm.provider).toBe("openai"));

    let providerUpdate!: Promise<void>;
    act(() => {
      providerUpdate = result.current.updateLLMProvider("anthropic", "", undefined, "sk-anthropic");
    });
    await vi.waitFor(() => expect(postCalls(fetchMock)).toHaveLength(1));

    act(() => {
      result.current.updateLLM("apiKey", "sk-wrong-provider");
      vi.advanceTimersByTime(1000);
    });
    expect(result.current.llm.apiKey).toBe("");

    await act(async () => {
      providerSave.resolve(new Response(JSON.stringify({
        status: "success",
        data: { provider: "anthropic", host: "", model: "gpt-4o" },
      })));
      await providerUpdate;
    });
    await Promise.resolve();

    expect(postCalls(fetchMock)).toHaveLength(1);
    expect(result.current.llm.provider).toBe("anthropic");
  });

  function postCalls(fetchMock: ReturnType<typeof mockFetchWithOpenAlgoConfig>) {
    return fetchMock.mock.calls.filter(
      (call) => (call[1] as RequestInit | undefined)?.method === "POST",
    );
  }

  it("persists model edits as a debounced partial backend patch", async () => {
    vi.useFakeTimers();
    const fetchMock = mockFetchWithOpenAlgoConfig();
    const { result } = renderHook(() => useSettingsState());
    await vi.waitFor(() => expect(result.current.llmHydrationState).toBe("ready"));

    act(() => {
      result.current.updateLLM("model", "qwen3:14b");
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
          body: JSON.stringify({ model: "qwen3:14b" }),
        }),
      );
    });
  });

  it("reports pending, saving, and saved states for a debounced LLM write", async () => {
    vi.useFakeTimers();
    const save = deferred<Response>();
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      if (init?.method === "POST" && String(input).includes("/config/llm")) return save.promise;
      if (String(input).includes("/config/llm")) {
        return new Response(JSON.stringify({
          status: "success",
          data: { provider: "openai", host: "", model: "gpt-4o" },
        }));
      }
      return new Response(JSON.stringify({ status: "success", data: {} }));
    });
    vi.stubGlobal("fetch", fetchMock);
    const { result } = renderHook(() => useSettingsState());
    await vi.waitFor(() => expect(result.current.llm.provider).toBe("openai"));

    act(() => result.current.updateLLM("model", "gpt-4.1"));
    expect(result.current.llmSaveState).toBe("pending");

    act(() => vi.advanceTimersByTime(1000));
    await vi.waitFor(() => expect(result.current.llmSaveState).toBe("saving"));

    await act(async () => {
      save.resolve(new Response(JSON.stringify({
        status: "success",
        data: { provider: "openai", host: "", model: "gpt-4.1" },
      })));
      await save.promise;
    });
    expect(result.current.llmSaveState).toBe("saved");
  });

  it("never routes API-key edits through generic debounced persistence", async () => {
    vi.useFakeTimers();
    const fetchMock = mockFetchWithOpenAlgoConfig(undefined, {
      provider: "openai",
      host: "",
      model: "gpt-4o-mini",
      api_key_configured: true,
      api_key_last4: "live",
    });
    const { result } = renderHook(() => useSettingsState());

    await vi.waitFor(() => expect(result.current.llm.provider).toBe("openai"));

    act(() => {
      result.current.updateLLM("apiKey", "s");
      result.current.updateLLM("apiKey", "sk");
      result.current.updateLLM("apiKey", "sk-live-1234");
      vi.advanceTimersByTime(1_000);
    });

    expect(postCalls(fetchMock)).toHaveLength(0);
    expect(result.current.llm.apiKey).toBe("");
  });

  it("coalesces rapid model edits into one debounced POST", async () => {
    vi.useFakeTimers();
    const fetchMock = mockFetchWithOpenAlgoConfig(undefined, {
      provider: "openai",
      host: "",
      model: "gpt-4o-mini",
      api_key_configured: false,
      api_key_last4: "",
    });
    const { result } = renderHook(() => useSettingsState());

    await vi.waitFor(() => expect(result.current.llm.provider).toBe("openai"));
    act(() => {
      result.current.updateLLM("model", "gpt-4o");
      result.current.updateLLM("model", "gpt-4.1");
    });

    act(() => {
      vi.advanceTimersByTime(1000);
    });
    vi.useRealTimers();

    await waitFor(() => {
      const posts = postCalls(fetchMock);
      expect(posts).toHaveLength(1);
      expect((posts[0][1] as RequestInit).body).toBe(
        JSON.stringify({ model: "gpt-4.1" }),
      );
    });
  });

  it("serialises an in-flight save and preserves the latest debounced edit", async () => {
    vi.useFakeTimers();
    const firstSave = deferred<Response>();
    let postCount = 0;
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      if (init?.method === "POST" && String(input).includes("/config/llm")) {
        postCount += 1;
        if (postCount === 1) return firstSave.promise;
        return new Response(JSON.stringify({ status: "success" }));
      }
      if (String(input).includes("/config/llm")) {
        return new Response(JSON.stringify({
          status: "success",
          data: { provider: "openai", host: "", model: "gpt-4o-mini" },
        }));
      }
      return new Response(JSON.stringify({ status: "success", data: {} }));
    });
    vi.stubGlobal("fetch", fetchMock);
    const { result } = renderHook(() => useSettingsState());

    await vi.waitFor(() => expect(result.current.llm.provider).toBe("openai"));
    act(() => {
      result.current.updateLLM("model", "gpt-4o");
      vi.advanceTimersByTime(1000);
    });
    await vi.waitFor(() => expect(postCalls(fetchMock)).toHaveLength(1));

    act(() => {
      result.current.updateLLM("model", "gpt-4.1");
      vi.advanceTimersByTime(1000);
    });
    expect(postCalls(fetchMock)).toHaveLength(1);

    await act(async () => {
      firstSave.resolve(new Response(JSON.stringify({ status: "success" })));
      await Promise.resolve();
    });
    await vi.waitFor(() => expect(postCalls(fetchMock)).toHaveLength(2));
    expect((postCalls(fetchMock)[1][1] as RequestInit).body).toBe(JSON.stringify({
      model: "gpt-4.1",
    }));
  });

  it("reapplies the latest queued edit after an older save rolls back", async () => {
    vi.useFakeTimers();
    const firstSave = deferred<Response>();
    let postCount = 0;
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      if (init?.method === "POST" && String(input).includes("/config/llm")) {
        postCount += 1;
        if (postCount === 1) return firstSave.promise;
        return new Response(JSON.stringify({
          status: "success",
          data: { provider: "openai", host: "", model: "gpt-4.1" },
        }));
      }
      if (String(input).includes("/config/llm")) {
        return new Response(JSON.stringify({
          status: "success",
          data: { provider: "openai", host: "", model: "gpt-4o-mini" },
        }));
      }
      return new Response(JSON.stringify({ status: "success", data: {} }));
    });
    vi.stubGlobal("fetch", fetchMock);
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    const { result } = renderHook(() => useSettingsState());

    await vi.waitFor(() => expect(result.current.llm.model).toBe("gpt-4o-mini"));
    act(() => {
      result.current.updateLLM("model", "gpt-4o");
      vi.advanceTimersByTime(1000);
    });
    await vi.waitFor(() => expect(postCalls(fetchMock)).toHaveLength(1));

    act(() => {
      result.current.updateLLM("model", "gpt-4.1");
      vi.advanceTimersByTime(1000);
    });
    await act(async () => {
      firstSave.resolve(new Response(
        JSON.stringify({ status: "error", message: "workspace locked" }),
        { status: 500 },
      ));
      await Promise.resolve();
    });

    await vi.waitFor(() => expect(postCalls(fetchMock)).toHaveLength(2));
    await vi.waitFor(() => expect(result.current.llm.model).toBe("gpt-4.1"));
    warnSpy.mockRestore();
  });

  it("surfaces a failed LLM save as a notification (never silently dropped)", async () => {
    vi.useFakeTimers();
    mockFetchWithFailedPost();
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    const { result } = renderHook(() => useSettingsState());
    await vi.waitFor(() => expect(result.current.llmHydrationState).toBe("ready"));

    act(() => {
      result.current.updateLLM("model", "bad-model");
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
    expect(result.current.llmSaveState).toBe("error");
    warnSpy.mockRestore();
  });

  it("flushes a pending LLM edit when the settings surface unmounts", async () => {
    vi.useFakeTimers();
    const fetchMock = mockFetchWithOpenAlgoConfig();
    const { result, unmount } = renderHook(() => useSettingsState());
    await vi.waitFor(() => expect(result.current.llmHydrationState).toBe("ready"));

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
    expect(typeof result.current.acceptConnection).toBe("function");
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
