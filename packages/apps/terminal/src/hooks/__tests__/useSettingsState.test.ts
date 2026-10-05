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
import {
  probeSettingsLlmHydration,
  useSettingsState,
} from "../useSettingsState";
import type { LlmProviderId } from "@/generated/serviceProviders";
import { useSettingsStore } from "@/stores/settingsStore";
import { useConnectionStore } from "@/stores/connectionStore";
import { useModeStore } from "@/stores/modeStore";
import { useAuthStore } from "@/stores/authStore";

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
  useModeStore.setState({ mode: "explore" });
  useAuthStore.setState({ token: null });
}

function mockFetchWithFailedLlmHydration(status = 401) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    if (String(input).includes("/config/llm") && init?.method !== "POST") {
      return new Response(
        JSON.stringify({
          status: "error",
          message: "LLM configuration requires an authenticated session",
        }),
        { status },
      );
    }
    return new Response(JSON.stringify({ status: "success", data: {} }));
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
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

function mockFetchWithLlmConfig(
  config: Record<string, unknown> = {
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
    mockFetchWithLlmConfig();
    mockEmitNotification.mockClear();
  });

  afterEach(() => {
    // LLM persistence is debounced with timers; a test that leaves fake timers
    // installed would poison the next one, so always restore real timers.
    vi.useRealTimers();
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

  it("accepts NVIDIA as a generated backend provider ID", async () => {
    const provider: LlmProviderId = "nvidia";
    mockFetchWithLlmConfig(undefined, {
      provider,
      host: "",
      model: "operator-selected-model",
      api_key_configured: true,
      api_key_last4: "idia",
    });

    const { result } = renderHook(() => useSettingsState());

    await waitFor(() => expect(result.current.llm.provider).toBe("nvidia"));
    expect(result.current.llm.model).toBe("operator-selected-model");
  });

  it("hydrates LLM config from the backend workspace endpoint without exposing the API key", async () => {
    mockFetchWithLlmConfig(undefined, {
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
    mockFetchWithLlmConfig(undefined, {
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
    const fetchMock = mockFetchWithLlmConfig(undefined, {
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
    const fetchMock = mockFetchWithLlmConfig(undefined, {
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
        .rejects.toThrow("Host URL is required for Custom (OpenAI-compatible)");
    });
    expect(postCalls(fetchMock)).toHaveLength(1);
  });

  it("does not accept a generic blank host edit for a credentialled provider", async () => {
    vi.useFakeTimers();
    const fetchMock = mockFetchWithLlmConfig(undefined, {
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
    const fetchMock = mockFetchWithLlmConfig(undefined, {
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
    const fetchMock = mockFetchWithLlmConfig(undefined, {
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
    const fetchMock = mockFetchWithLlmConfig(undefined, {
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
    const fetchMock = mockFetchWithLlmConfig(undefined, {
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

  function postCalls(fetchMock: ReturnType<typeof mockFetchWithLlmConfig>) {
    return fetchMock.mock.calls.filter(
      (call) => (call[1] as RequestInit | undefined)?.method === "POST",
    );
  }

  it("persists model edits as a debounced partial backend patch", async () => {
    vi.useFakeTimers();
    const fetchMock = mockFetchWithLlmConfig();
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
    const fetchMock = mockFetchWithLlmConfig(undefined, {
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
    const fetchMock = mockFetchWithLlmConfig(undefined, {
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
    const fetchMock = mockFetchWithLlmConfig();
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

  it("treats an Explore LLM load failure as an empty unconfigured state, not a broken session", async () => {
    useModeStore.setState({ mode: "explore" });
    useAuthStore.setState({ token: "demo-user" });
    mockFetchWithFailedLlmHydration();
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});

    const { result } = renderHook(() => useSettingsState());

    await waitFor(() => expect(result.current.llmHydrationState).toBe("empty"));
    expect(typeof result.current.retryLlmHydration).toBe("function");
    warnSpy.mockRestore();
  });

  it("retries Explore LLM hydration and becomes ready when the session can load config", async () => {
    useModeStore.setState({ mode: "explore" });
    useAuthStore.setState({ token: "demo-user" });
    let llmAttempts = 0;
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      if (String(input).includes("/config/llm") && init?.method !== "POST") {
        llmAttempts += 1;
        if (llmAttempts === 1) {
          return new Response(
            JSON.stringify({
              status: "error",
              message: "LLM configuration requires an authenticated session",
            }),
            { status: 401 },
          );
        }
        return new Response(JSON.stringify({
          status: "success",
          data: { provider: "ollama", host: "", model: "", api_key_configured: false },
        }));
      }
      return new Response(JSON.stringify({ status: "success", data: {} }));
    });
    vi.stubGlobal("fetch", fetchMock);
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    const { result } = renderHook(() => useSettingsState());

    await waitFor(() => expect(result.current.llmHydrationState).toBe("empty"));

    act(() => {
      result.current.retryLlmHydration();
    });

    await waitFor(() => expect(result.current.llmHydrationState).toBe("ready"));
    expect(llmAttempts).toBe(2);
    warnSpy.mockRestore();
  });

  it("probes Settings #llm hydration the same way Chat aligns with the empty appearance", async () => {
    useModeStore.setState({ mode: "explore" });
    useAuthStore.setState({ token: "demo-user" });
    mockFetchWithFailedLlmHydration();
    await expect(probeSettingsLlmHydration()).resolves.toBe("empty");

    useModeStore.setState({ mode: "live" });
    useAuthStore.setState({ token: "session-jwt" });
    await expect(probeSettingsLlmHydration()).resolves.toBe("error");

    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({
      status: "success",
      data: { provider: "openai", model: "test" },
    }))));
    await expect(probeSettingsLlmHydration()).resolves.toBe("ready");
  });

  it.each(["explore", "practice", "live"] as const)(
    "treats a successful Settings read with no stored provider as empty in %s — global config truth, not Mode",
    async (mode) => {
      useModeStore.setState({ mode });
      useAuthStore.setState({ token: mode === "explore" ? "demo-user" : `${mode}-jwt` });
      vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({
        status: "success",
        data: { provider: "", model: "", api_key_configured: false },
      }))));
      await expect(probeSettingsLlmHydration()).resolves.toBe("empty");
    },
  );

  it("keeps a Live LLM load failure as a protected error, not an empty Explore fallback", async () => {
    useModeStore.setState({ mode: "live" });
    useAuthStore.setState({ token: "session-jwt" });
    mockFetchWithFailedLlmHydration();
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});

    const { result } = renderHook(() => useSettingsState());

    await waitFor(() => expect(result.current.llmHydrationState).toBe("error"));
    warnSpy.mockRestore();
  });
});
