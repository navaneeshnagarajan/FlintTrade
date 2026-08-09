/**
 * AIAdvisorWidget.test.tsx
 *
 * Tests for the AI Advisor chat widget.
 * Verifies rendering, not-configured state, and chat input.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";

// ---------------------------------------------------------------------------
// Mocks — must be defined before component import
// ---------------------------------------------------------------------------

// Mock settingsStore — default: LLM not configured
const mockLlmProvider = vi.fn(() => "");

vi.mock("@/stores/settingsStore", () => ({
  useSettingsStore: (selector: (s: Record<string, unknown>) => unknown) =>
    selector({
      llm: { provider: mockLlmProvider(), model: "" },
    }),
}));

// Mock aiConversationStore with the same callable/getState/setState surface used
// by the widget so request-body tests cross the real compose/send path.
const conversationStoreMock = vi.hoisted(() => {
  const state: {
    messages: Array<Record<string, unknown>>;
    isStreaming: boolean;
    currentRoute: string;
    conversationId: string | null;
  } = {
    messages: [],
    isStreaming: false,
    currentRoute: "/ai",
    conversationId: null,
  };
  let nextId = 0;
  const addMessage = vi.fn((role: string, content: string) => {
    state.messages.push({
      id: `mock-${++nextId}`,
      role,
      content,
      timestamp: 1,
      route: state.currentRoute,
    });
  });
  const setStreaming = vi.fn((value: boolean) => { state.isStreaming = value; });
  const clearMessages = vi.fn(() => { state.messages = []; });
  const snapshot = () => ({ ...state, addMessage, setStreaming, clearMessages });
  const useStore = Object.assign(
    vi.fn((selector: (value: ReturnType<typeof snapshot>) => unknown) => selector(snapshot())),
    {
      getState: snapshot,
      setState: vi.fn((update: Record<string, unknown> | ((value: ReturnType<typeof snapshot>) => Record<string, unknown>)) => {
        const next = typeof update === "function" ? update(snapshot()) : update;
        Object.assign(state, next);
      }),
    },
  );
  const reset = () => {
    state.messages = [];
    state.isStreaming = false;
    state.currentRoute = "/ai";
    state.conversationId = null;
    nextId = 0;
    addMessage.mockClear();
    setStreaming.mockClear();
    clearMessages.mockClear();
    useStore.mockClear();
    useStore.setState.mockClear();
  };
  return { useStore, reset };
});

vi.mock("@/stores/aiConversationStore", () => ({
  useAIConversationStore: conversationStoreMock.useStore,
}));

// Mock advisorApi
vi.mock("@/services/advisorApi", () => ({
  getAdvisorBase: () => "",
}));

// Mock the shared gated order client — approvals must dispatch through it,
// never through a raw fetch of a model-chosen endpoint.
const mockPlaceOrder = vi.fn();
vi.mock("@/services/api", () => ({
  placeOrder: (params: unknown) => mockPlaceOrder(params) as Promise<{ orderId: string }>,
}));

// AI2 history clients — mocked so the panel is hermetic.
const mockListSessions = vi.fn();
const mockSearchSessions = vi.fn();
const mockGetSession = vi.fn();
vi.mock("@/services/ftApi.ai", () => ({
  listAiSessions: (limit: number) => mockListSessions(limit) as Promise<unknown>,
  searchAiSessions: (q: string) => mockSearchSessions(q) as Promise<unknown>,
  getAiSession: (id: string) => mockGetSession(id) as Promise<unknown>,
}));

// Mock fetch to prevent real network calls (fetchAdvisorStatus on mount)
vi.spyOn(globalThis, "fetch").mockRejectedValue(new Error("No backend"));

// ---------------------------------------------------------------------------
// Import component under test (after mocks)
// ---------------------------------------------------------------------------

import AIAdvisorWidget, {
  executeApprovedToolCall,
  normaliseToolEndpoint,
  toPlaceOrderParams,
} from "../AIAdvisorWidget";
import { useModeStore } from "@/stores/modeStore";

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

function Providers({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

describe("AIAdvisorWidget", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    conversationStoreMock.reset();
    mockLlmProvider.mockReturnValue("");
    vi.spyOn(globalThis, "fetch").mockRejectedValue(new Error("No backend"));
  });

  it("renders without crashing", () => {
    render(<AIAdvisorWidget />, { wrapper: Providers });
    expect(screen.getByText("AI Advisor")).toBeInTheDocument();
  });

  it("shows not-configured state when LLM provider is empty", () => {
    render(<AIAdvisorWidget />, { wrapper: Providers });
    expect(screen.getByText("Not configured")).toBeInTheDocument();
    expect(screen.getByText("LLM Not Configured")).toBeInTheDocument();
  });

  it("has a chat input field", () => {
    render(<AIAdvisorWidget />, { wrapper: Providers });
    expect(
      screen.getByPlaceholderText("Configure LLM in Settings first..."),
    ).toBeInTheDocument();
  });

  it("has a send button", () => {
    render(<AIAdvisorWidget />, { wrapper: Providers });
    expect(screen.getByRole("button", { name: /send message/i })).toBeInTheDocument();
  });

  it("does not auto-submit and sends exact analysis context in the SSE request body", async () => {
    mockLlmProvider.mockReturnValue("openai");
    const fetchMock = vi.mocked(globalThis.fetch);
    fetchMock.mockImplementation(async (input, init) => {
      const url = String(input);
      if (init?.method === "POST" && url.endsWith("/api/v1/advisor/stream")) {
        return new Response('data: {"token":"Done"}\n\ndata: {"done":true}\n\n', { status: 200 });
      }
      return new Response(JSON.stringify({
        status: "success",
        data: { configured: true, provider: "openai", model: "test" },
      }), { status: 200, headers: { "Content-Type": "application/json" } });
    });
    const analysisContext = { symbol: "RELIANCE", exchange: "NSE", source: "palette" } as const;

    render(<AIAdvisorWidget analysisContext={analysisContext} />, { wrapper: Providers });
    expect(fetchMock.mock.calls.filter(([, init]) => init?.method === "POST")).toHaveLength(0);

    fireEvent.change(screen.getByPlaceholderText("Ask the AI advisor..."), {
      target: { value: "Analyse this instrument" },
    });
    fireEvent.click(screen.getByRole("button", { name: /send message/i }));

    await waitFor(() => {
      expect(fetchMock.mock.calls.filter(([, init]) => init?.method === "POST")).toHaveLength(1);
    });
    const [, init] = fetchMock.mock.calls.find(([, request]) => request?.method === "POST")!;
    expect(JSON.parse(String(init?.body))).toEqual({
      messages: [{ role: "user", content: "Analyse this instrument" }],
      context: analysisContext,
    });
  });

  it("sends the same exact analysis context in streaming and non-streaming fallback bodies", async () => {
    mockLlmProvider.mockReturnValue("openai");
    const fetchMock = vi.mocked(globalThis.fetch);
    fetchMock.mockImplementation(async (input, init) => {
      const url = String(input);
      if (init?.method !== "POST") {
        return new Response(JSON.stringify({ status: "error" }), { status: 200 });
      }
      if (url.endsWith("/api/v1/advisor/stream")) {
        return new Response(null, { status: 404 });
      }
      return new Response(JSON.stringify({
        status: "success",
        data: { response: "Fallback answer" },
      }), { status: 200, headers: { "Content-Type": "application/json" } });
    });
    const analysisContext = { symbol: "NIFTY-26MAR-FUT", exchange: "NFO", source: "palette" } as const;

    render(<AIAdvisorWidget analysisContext={analysisContext} />, { wrapper: Providers });
    fireEvent.change(screen.getByPlaceholderText("Ask the AI advisor..."), {
      target: { value: "What changed?" },
    });
    fireEvent.click(screen.getByRole("button", { name: /send message/i }));

    await waitFor(() => {
      expect(fetchMock.mock.calls.filter(([, init]) => init?.method === "POST")).toHaveLength(2);
    });
    const postBodies = fetchMock.mock.calls
      .filter(([, init]) => init?.method === "POST")
      .map(([, init]) => JSON.parse(String(init?.body)) as Record<string, unknown>);
    expect(postBodies[0]).toEqual({
      messages: [{ role: "user", content: "What changed?" }],
      context: analysisContext,
    });
    expect(postBodies[1]).toEqual({
      messages: [{ role: "user", content: "What changed?" }],
      message: "What changed?",
      context: analysisContext,
    });
  });
});

describe("normaliseToolEndpoint", () => {
  it("normalises every place-order spelling to the same key", () => {
    expect(normaliseToolEndpoint("/api/v1/orders/place")).toBe("orders/place");
    expect(normaliseToolEndpoint("orders/place")).toBe("orders/place");
    expect(normaliseToolEndpoint("/ft-api/api/v1/orders/place/")).toBe("orders/place");
    expect(normaliseToolEndpoint("http://127.0.0.1:5100/api/v1/orders/place")).toBe("orders/place");
    expect(normaliseToolEndpoint("PLACEORDER")).toBe("placeorder");
  });

  it("leaves non-order endpoints distinguishable", () => {
    expect(normaliseToolEndpoint("/api/v1/native/accounts")).toBe("native/accounts");
    expect(normaliseToolEndpoint("/v1/auth/pin")).toBe("auth/pin");
  });
});

describe("toPlaceOrderParams", () => {
  const valid = {
    symbol: "NIFTY24JUL25000CE",
    exchange: "nfo",
    action: "buy",
    quantity: 75,
    orderType: "LIMIT",
    product: "NRML",
    price: 12.5,
  };

  it("accepts a complete explicit order and stamps the AIAdvisor strategy", () => {
    const params = toPlaceOrderParams(valid);
    expect(params).toMatchObject({
      symbol: "NIFTY24JUL25000CE",
      exchange: "NFO",
      action: "BUY",
      quantity: 75,
      orderType: "LIMIT",
      product: "NRML",
      price: 12.5,
      strategy: "AIAdvisor",
    });
  });

  it.each([
    ["missing symbol", { ...valid, symbol: "" }],
    ["missing exchange", { ...valid, exchange: undefined }],
    ["bad action", { ...valid, action: "HOLD" }],
    ["zero quantity", { ...valid, quantity: 0 }],
    ["fractional quantity", { ...valid, quantity: 7.5 }],
    ["missing orderType", { ...valid, orderType: undefined }],
    ["bad product", { ...valid, product: "SUPER" }],
    ["negative price", { ...valid, price: -1 }],
    ["non-numeric trigger", { ...valid, triggerPrice: "abc" }],
  ])("refuses an order with %s — no silent defaults", (_label, payload) => {
    expect(toPlaceOrderParams(payload as Record<string, unknown>)).toBeNull();
  });
});

describe("executeApprovedToolCall", () => {
  // The store defaults to `explore`, and these tests ran in it — one asserted
  // the BACKEND refusal message, which is precisely how the missing client
  // mode gate stayed invisible.
  beforeEach(() => {
    mockPlaceOrder.mockReset();
    useModeStore.setState({ mode: "live" });
  });
  afterEach(() => {
    useModeStore.setState({ mode: "explore" });
  });

  const orderCall = {
    description: "Buy NIFTY call",
    endpoint: "/api/v1/orders/place",
    method: "POST",
    payload: {
      symbol: "NIFTY24JUL25000CE",
      exchange: "NFO",
      action: "BUY",
      quantity: 75,
      orderType: "MARKET",
      product: "NRML",
    },
  };

  it("dispatches an approvable order through the shared gated client", async () => {
    mockPlaceOrder.mockResolvedValueOnce({ orderId: "FT-123" });
    const outcome = await executeApprovedToolCall(orderCall);
    expect(mockPlaceOrder).toHaveBeenCalledOnce();
    expect(mockPlaceOrder).toHaveBeenCalledWith(
      expect.objectContaining({ symbol: "NIFTY24JUL25000CE", strategy: "AIAdvisor" }),
    );
    expect(outcome.executed).toBe(true);
    expect(outcome.message).toContain("FT-123");
  });

  it("refuses to dispatch in Explore mode", async () => {
    useModeStore.setState({ mode: "explore" });
    const outcome = await executeApprovedToolCall(orderCall);

    expect(mockPlaceOrder).not.toHaveBeenCalled();
    expect(outcome.executed).toBe(false);
    expect(outcome.message).toContain("Connect a broker");
  });

  it("refuses a LIMIT order priced at zero", async () => {
    // A model-composed LIMIT with price 0 passed every field check: the price
    // branch rejected only negatives. The operator would have approved a card
    // showing "LIMIT" with no price to sanity-check.
    const outcome = await executeApprovedToolCall({
      ...orderCall,
      payload: { ...orderCall.payload, orderType: "LIMIT", price: 0 },
    });

    expect(mockPlaceOrder).not.toHaveBeenCalled();
    expect(outcome.executed).toBe(false);
  });

  it("refuses an SL order with no trigger price", async () => {
    const outcome = await executeApprovedToolCall({
      ...orderCall,
      payload: { ...orderCall.payload, orderType: "SL", price: 100 },
    });

    expect(mockPlaceOrder).not.toHaveBeenCalled();
    expect(outcome.executed).toBe(false);
  });

  it("still dispatches a well-formed LIMIT order", async () => {
    mockPlaceOrder.mockResolvedValueOnce({ orderId: "FT-9" });
    const outcome = await executeApprovedToolCall({
      ...orderCall,
      payload: { ...orderCall.payload, orderType: "LIMIT", price: 123.5 },
    });

    expect(mockPlaceOrder).toHaveBeenCalledOnce();
    expect(outcome.executed).toBe(true);
  });

  it("refuses a non-allowlisted endpoint without any dispatch", async () => {
    const outcome = await executeApprovedToolCall({
      ...orderCall,
      endpoint: "/api/v1/native/accounts",
    });
    expect(mockPlaceOrder).not.toHaveBeenCalled();
    expect(outcome.executed).toBe(false);
    expect(outcome.message).toContain("not an approvable action");
    expect(outcome.message).toContain("/api/v1/native/accounts");
  });

  it("refuses an incomplete order payload without any dispatch", async () => {
    const outcome = await executeApprovedToolCall({
      ...orderCall,
      payload: { symbol: "NIFTY", action: "BUY" },
    });
    expect(mockPlaceOrder).not.toHaveBeenCalled();
    expect(outcome.executed).toBe(false);
    expect(outcome.message).toContain("Nothing was sent to the broker");
  });

  it("reports a failed placement honestly — never 'executed successfully'", async () => {
    mockPlaceOrder.mockRejectedValueOnce(new Error("Live order blocked: mode_blocked"));
    const outcome = await executeApprovedToolCall(orderCall);
    expect(outcome.executed).toBe(false);
    expect(outcome.message).toContain("Order failed: Live order blocked: mode_blocked");
    expect(outcome.message).not.toContain("submitted");
  });
});


describe("AIAdvisorWidget history panel", () => {
  function renderWithClient() {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    return render(
      <QueryClientProvider client={client}>
        <AIAdvisorWidget />
      </QueryClientProvider>,
    );
  }

  beforeEach(() => {
    mockListSessions.mockReset();
    mockSearchSessions.mockReset();
    mockGetSession.mockReset();
    mockListSessions.mockResolvedValue([
      {
        id: "s1",
        surface: "advisor",
        title: "What is the max pain on BANKNIFTY?",
        started_at: "2026-07-19T10:00:00Z",
        last_at: "2026-07-19T10:05:00Z",
        message_count: 4,
      },
    ]);
  });

  it("lists stored sessions when the history toggle opens", async () => {
    renderWithClient();
    fireEvent.click(screen.getByLabelText("Browse past sessions"));
    expect(
      await screen.findByText(/What is the max pain on BANKNIFTY\?/),
    ).toBeInTheDocument();
    expect(mockListSessions).toHaveBeenCalledWith(50);
  });

  it("opens a stored session read-only and returns via Back", async () => {
    mockGetSession.mockResolvedValue({
      id: "s1",
      surface: "advisor",
      title: "What is the max pain on BANKNIFTY?",
      started_at: "2026-07-19T10:00:00Z",
      last_at: "2026-07-19T10:05:00Z",
      messages: [
        { id: "m1", role: "user", content: "What is the max pain?", created_at: "t" },
        { id: "m2", role: "assistant", content: "Near 51000.", created_at: "t" },
      ],
    });
    renderWithClient();
    fireEvent.click(screen.getByLabelText("Browse past sessions"));
    fireEvent.click(await screen.findByText(/What is the max pain on BANKNIFTY\?/));

    expect(await screen.findByText("Near 51000.")).toBeInTheDocument();
    expect(screen.getByText(/read-only/i)).toBeInTheDocument();

    fireEvent.click(screen.getByLabelText("Back to session list"));
    await waitFor(() =>
      expect(screen.queryByText("Near 51000.")).not.toBeInTheDocument(),
    );
  });

  it("searches stored sessions", async () => {
    mockSearchSessions.mockResolvedValue([
      {
        id: "m9",
        session_id: "s1",
        role: "assistant",
        created_at: "t",
        surface: "advisor",
        title: "What is the max pain on BANKNIFTY?",
        snippet: "Max pain sits near [51000]",
      },
    ]);
    renderWithClient();
    fireEvent.click(screen.getByLabelText("Browse past sessions"));
    fireEvent.change(await screen.findByLabelText("Search past sessions"), {
      target: { value: "51000" },
    });
    expect(await screen.findByText(/Max pain sits near/)).toBeInTheDocument();
    expect(mockSearchSessions).toHaveBeenCalledWith("51000");
  });
});
