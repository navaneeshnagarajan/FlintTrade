/**
 * AIAdvisorWidget.test.tsx
 *
 * Tests for the AI Advisor chat widget.
 * Verifies rendering, not-configured state, and chat input.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
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

// Mock aiConversationStore
vi.mock("@/stores/aiConversationStore", () => ({
  useAIConversationStore: (selector: (s: Record<string, unknown>) => unknown) =>
    selector({
      messages: [],
      isStreaming: false,
      addMessage: vi.fn(),
      setStreaming: vi.fn(),
      clearMessages: vi.fn(),
    }),
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
  beforeEach(() => {
    mockPlaceOrder.mockReset();
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
