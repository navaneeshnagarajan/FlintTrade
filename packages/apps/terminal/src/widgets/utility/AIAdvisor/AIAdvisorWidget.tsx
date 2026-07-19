/**
 * AIAdvisorWidget — chat interface for the FlintTrade AI trading advisor.
 *
 * Wired to the FlintTrade Python backend at /ft-api/api/v1/advisor.
 * Features:
 *   - Conversation memory: full message history sent on each request
 *   - Shared store (aiConversationStore) — persisted via Zustand, shared with AITutorPill
 *   - SSE streaming responses with token-by-token rendering
 *   - Fallback to non-streaming endpoint on 404
 *   - MCP tool confirmation cards (Approve / Reject)
 *   - Clear chat button
 *   - "Not configured" state with guidance to Settings when LLM provider is unset
 *   - Checks advisor/status on mount to sync LLM config state
 */

import { useState, useRef, useEffect, useCallback, type KeyboardEvent, memo } from "react";
import { safeParse, sseTokenSchema, wsMessageSchema } from "@/lib/safeParse";
import { AdvisorStatusResponseSchema, AdvisorResponseSchema } from "@/lib/schemas/ftApi";
import { Send, Bot, User, Loader2, Settings, Trash2 } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { useSettingsStore } from "@/stores/settingsStore";
import { useAIConversationStore } from "@/stores/aiConversationStore";
import { useAuthStore } from "@/stores/authStore";
import { getAdvisorBase } from "@/services/advisorApi";
import { placeOrder } from "@/services/api";
import type { PlaceOrderParams } from "@/types/api";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const TOOL_CALL_PATTERN = /\[TOOL_CALL:([\s\S]*?)\]/;

/**
 * Endpoint spellings (normalised: prefix-stripped, lowercased) the approval
 * card may execute. Only gated order placement is approvable — the widget
 * must never POST an arbitrary model-chosen endpoint with the operator's
 * session, so anything outside this set is refused with the endpoint named.
 */
const APPROVABLE_ORDER_ENDPOINTS = new Set(["orders/place", "placeorder", "place-order"]);

const ORDER_ACTIONS = new Set(["BUY", "SELL"]);
const ORDER_TYPES = new Set(["MARKET", "LIMIT", "SL", "SL-M"]);
const ORDER_PRODUCTS = new Set(["MIS", "CNC", "NRML"]);

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface ToolCall {
  endpoint: string;
  method: string;
  description: string;
  payload: Record<string, unknown>;
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  timestamp: number;
  toolCall?: ToolCall;
  toolStatus?: "pending" | "approved" | "rejected" | "failed";
}

// AdvisorResponse and AdvisorStatusResponse are validated via ftApi schemas;
// keep local type aliases for the inferred shapes used below.
type AdvisorResponse = {
  status: "success" | "error";
  data?: { response: string };
  message?: string;
};
type AdvisorStatusResponse = {
  status: "success" | "error";
  data?: { configured: boolean; provider: string; model: string };
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function generateId(): string {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;
}

function fmtTime(ts: number): string {
  return new Date(ts).toLocaleTimeString("en-IN", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

/**
 * Parse tool call from assistant message content.
 * Supports `[TOOL_CALL:...]` pattern and JSON `{"type":"tool_call",...}` blocks.
 */
function parseToolCall(content: string): ToolCall | undefined {
  // Pattern 1: [TOOL_CALL:description|endpoint|method|payload_json]
  const match = TOOL_CALL_PATTERN.exec(content);
  if (match) {
    const parts = match[1].split("|").map((s) => s.trim());
    if (parts.length >= 3) {
      let payload: Record<string, unknown> = {};
      if (parts[3]) {
        // Payload is arbitrary JSON from the AI — validate it's an object, allow any keys.
        payload = (safeParse(parts[3], wsMessageSchema) ?? {}) as Record<string, unknown>;
      }
      return {
        description: parts[0],
        endpoint: parts[1],
        method: parts[2].toUpperCase(),
        payload,
      };
    }
  }

  // Pattern 2: JSON block with type: "tool_call"
  const jsonMatch = /\{[\s\S]*"type"\s*:\s*"tool_call"[\s\S]*\}/.exec(content);
  if (jsonMatch) {
    const parsed = safeParse(jsonMatch[0], wsMessageSchema);
    if (parsed && parsed["type"] === "tool_call") {
      return {
        description: (parsed["description"] as string) ?? "Execute action",
        endpoint: (parsed["endpoint"] as string) ?? "",
        method: ((parsed["method"] as string) ?? "POST").toUpperCase(),
        payload: (parsed["payload"] as Record<string, unknown>) ?? {},
      };
    }
  }

  return undefined;
}

/**
 * Strip host/prefix noise from a model-emitted endpoint so it can be compared
 * against the approvable allowlist (`/api/v1/orders/place`, `orders/place`,
 * `placeorder`… all normalise to the same key).
 */
export function normaliseToolEndpoint(endpoint: string): string {
  return endpoint
    .replace(/^https?:\/\/[^/]+/i, "")
    .replace(/^\/?(ft-api\/)?(api\/)?v1\//i, "")
    .replace(/^\/+/, "")
    .replace(/\/+$/, "")
    .toLowerCase();
}

/**
 * Validate a model-emitted payload into complete PlaceOrderParams.
 *
 * Every core field must be explicit — an AI-proposed order gets no silent
 * defaults. Returns null (→ honest refusal) when anything is missing or
 * malformed; deep validation (price bands, lot size) stays with the backend
 * safety layers.
 */
export function toPlaceOrderParams(payload: Record<string, unknown>): PlaceOrderParams | null {
  const symbol = typeof payload["symbol"] === "string" ? payload["symbol"].trim() : "";
  const exchange = typeof payload["exchange"] === "string" ? payload["exchange"].trim().toUpperCase() : "";
  const action = typeof payload["action"] === "string" ? payload["action"].trim().toUpperCase() : "";
  const rawOrderType = payload["orderType"] ?? payload["order_type"] ?? payload["pricetype"];
  const orderType = typeof rawOrderType === "string" ? rawOrderType.trim().toUpperCase() : "";
  const rawProduct = payload["product"];
  const product = typeof rawProduct === "string" ? rawProduct.trim().toUpperCase() : "";
  const quantity = Number(payload["quantity"]);

  if (!symbol || !exchange) return null;
  if (!ORDER_ACTIONS.has(action)) return null;
  if (!ORDER_TYPES.has(orderType)) return null;
  if (!ORDER_PRODUCTS.has(product)) return null;
  if (!Number.isInteger(quantity) || quantity <= 0) return null;

  const params: PlaceOrderParams = {
    symbol,
    exchange,
    action: action as PlaceOrderParams["action"],
    quantity,
    orderType: orderType as PlaceOrderParams["orderType"],
    product: product as PlaceOrderParams["product"],
    strategy: "AIAdvisor",
  };

  const rawPrice = payload["price"];
  if (rawPrice !== undefined && rawPrice !== null && rawPrice !== "") {
    const price = Number(rawPrice);
    if (!Number.isFinite(price) || price < 0) return null;
    params.price = price;
  }
  const rawTrigger = payload["triggerPrice"] ?? payload["trigger_price"];
  if (rawTrigger !== undefined && rawTrigger !== null && rawTrigger !== "") {
    const triggerPrice = Number(rawTrigger);
    if (!Number.isFinite(triggerPrice) || triggerPrice < 0) return null;
    params.triggerPrice = triggerPrice;
  }
  return params;
}

/**
 * Execute an operator-approved tool call and return the chat message that
 * reports the outcome.
 *
 * Only gated order placement is executable. Everything routes through the
 * shared placeOrder client (auth headers, order rate limit, fail-closed
 * native write-target assertion, actionable backend errors) or is refused
 * with the endpoint named — the widget must never POST an arbitrary
 * model-chosen endpoint with the operator's session, and must never report
 * success for a failed request.
 */
export interface ApprovedToolCallOutcome {
  /** Chat message reporting what happened. */
  message: string;
  /** True only when the order was actually submitted successfully. */
  executed: boolean;
}

export async function executeApprovedToolCall(toolCall: ToolCall): Promise<ApprovedToolCallOutcome> {
  const endpointKey = normaliseToolEndpoint(toolCall.endpoint);
  if (!APPROVABLE_ORDER_ENDPOINTS.has(endpointKey)) {
    return {
      executed: false,
      message:
        `Action not executed: "${toolCall.endpoint}" is not an approvable action. ` +
        "Only order placement through the gated order path can be approved here.",
    };
  }

  const params = toPlaceOrderParams(toolCall.payload);
  if (!params) {
    return {
      executed: false,
      message:
        "Action not executed: the proposed order is missing or malforms a required field " +
        "(symbol, exchange, action, quantity, orderType, product). Nothing was sent to the broker.",
    };
  }

  try {
    const result = await placeOrder(params);
    return {
      executed: true,
      message:
        `Order submitted through the gated order path — order ID ${result.orderId}.\n\n` +
        `\`${params.action} ${params.quantity} × ${params.symbol} (${params.exchange}) ` +
        `${params.orderType} ${params.product}\``,
    };
  } catch (err: unknown) {
    const errText = err instanceof Error ? err.message : String(err);
    return { executed: false, message: `Order failed: ${errText}` };
  }
}

/**
 * Check if the LLM provider is configured in the settings store.
 */
function useIsAIConfigured(): boolean {
  return useSettingsStore((s) => s.llm.provider.length > 0);
}

/**
 * Fetch advisor status from the backend and sync LLM config into the settings store.
 */
async function fetchAdvisorStatus(): Promise<void> {
  try {
    const token = useAuthStore.getState().token;
    if (!token || token === "demo-user" || token === "dev-bypass") return;
    const base = getAdvisorBase();
    const resp = await fetch(`${base}/api/v1/advisor/status`);
    if (!resp.ok) return;
    const raw: unknown = await resp.json();
    const result = AdvisorStatusResponseSchema.safeParse(raw);
    if (!result.success) {
      console.error("[AIAdvisorWidget] /advisor/status shape mismatch:", result.error.issues);
      return;
    }
    const json = result.data as AdvisorStatusResponse;
    if (json.status === "success" && json.data) {
      useSettingsStore.getState().setLLM({
        provider: json.data.provider,
        model: json.data.model,
      });
    }
  } catch {
    // Backend may not be running — leave settings as-is
  }
}

/**
 * POST full conversation to the streaming endpoint (SSE).
 * Calls onToken for each chunk. Returns full assembled text.
 * Throws if the endpoint is not available (404 triggers fallback).
 */
async function streamAdvisorMessage(
  messages: Array<{ role: string; content: string }>,
  onToken: (token: string, fullText: string) => void,
  signal?: AbortSignal,
): Promise<string> {
  const base = getAdvisorBase();
  const resp = await fetch(`${base}/api/v1/advisor/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ messages }),
    signal,
  });

  if (resp.status === 404) {
    throw new Error("STREAMING_NOT_AVAILABLE");
  }

  if (!resp.ok) {
    throw new Error(`Advisor API: HTTP ${resp.status}`);
  }

  const reader = resp.body?.getReader();
  if (!reader) {
    throw new Error("No readable stream in response");
  }

  const decoder = new TextDecoder();
  let assistantText = "";

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      const chunk = decoder.decode(value, { stream: true });
      let streamDone = false;
      for (const line of chunk.split("\n")) {
        if (!line.startsWith("data: ")) continue;
        const raw = line.slice(6).trim();
        if (!raw || raw === "[DONE]") continue;
        const data = safeParse(raw, sseTokenSchema);
        if (!data) continue;
        if (data.done) { streamDone = true; break; }
        if (data.token) {
          assistantText += data.token;
          onToken(data.token, assistantText);
        }
      }
      if (streamDone) break;
    }
  } finally {
    try { await reader.cancel(); } catch { /* already cancelled */ }
    reader.releaseLock();
  }

  return assistantText;
}

/**
 * POST full conversation to the non-streaming advisor endpoint (fallback).
 */
async function postAdvisorMessage(
  messages: Array<{ role: string; content: string }>,
  signal?: AbortSignal,
): Promise<string> {
  const base = getAdvisorBase();
  const resp = await fetch(`${base}/api/v1/advisor`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      messages,
      // Legacy single-message field for backwards compat
      message: messages[messages.length - 1]?.content ?? "",
      context: "",
    }),
    signal,
  });

  if (!resp.ok) {
    throw new Error(`Advisor API: HTTP ${resp.status}`);
  }

  const raw: unknown = await resp.json();
  const result = AdvisorResponseSchema.safeParse(raw);
  if (!result.success) {
    console.error("[AIAdvisorWidget] /advisor response shape mismatch:", result.error.issues);
    return "Unexpected response format from advisor.";
  }
  const json = result.data as AdvisorResponse;

  if (json.status === "error") {
    return json.message ?? "Unknown error from advisor.";
  }

  return json.data?.response ?? "No response from advisor.";
}

// ---------------------------------------------------------------------------
// Tool Confirmation Card
// ---------------------------------------------------------------------------

interface ToolCardProps {
  toolCall: ToolCall;
  status: "pending" | "approved" | "rejected" | "failed";
  onApprove: () => void;
  onReject: () => void;
}

function ToolCard({ toolCall, status, onApprove, onReject }: ToolCardProps) {
  // The card must show what WOULD ACTUALLY EXECUTE — the validated payload —
  // not the model's free-text description, which a prompt-injected model
  // could arbitrage against the payload ("Buy 1 RELIANCE" describing a
  // SELL 1800). Non-approvable or malformed calls get no Approve button.
  const approvable = APPROVABLE_ORDER_ENDPOINTS.has(normaliseToolEndpoint(toolCall.endpoint));
  const params = approvable ? toPlaceOrderParams(toolCall.payload) : null;

  return (
    <div className="bg-surface-card border border-border-default rounded-lg p-3">
      <div className="text-xxs text-text-muted uppercase tracking-wider mb-1">
        AI proposes this order
      </div>
      {params ? (
        <div className="font-mono text-sm font-bold text-text-primary">
          {params.action} {params.quantity} × {params.symbol} ({params.exchange}){" "}
          {params.orderType} {params.product}
          {params.price !== undefined && ` @ ${params.price}`}
          {params.triggerPrice !== undefined && ` trg ${params.triggerPrice}`}
        </div>
      ) : (
        <div className="text-xs text-loss">
          {approvable
            ? "Malformed order proposal — a required field is missing or invalid. It cannot be approved."
            : `Not an approvable action (${toolCall.method} ${toolCall.endpoint}). Only gated order placement can be approved here.`}
        </div>
      )}
      {toolCall.description && (
        <div className="text-xxs text-text-muted mt-1">
          Model's description: {toolCall.description}
        </div>
      )}
      {status === "pending" ? (
        <div className="flex gap-2 mt-3">
          {params && (
            <button
              type="button"
              onClick={onApprove}
              className="px-4 py-1.5 text-xs font-semibold rounded bg-profit/10 text-profit border border-profit/30 hover:bg-profit/20 transition-colors"
            >
              Approve
            </button>
          )}
          <button
            type="button"
            onClick={onReject}
            className="px-4 py-1.5 text-xs font-semibold rounded bg-loss/10 text-loss border border-loss/30 hover:bg-loss/20 transition-colors"
          >
            {params ? "Reject" : "Dismiss"}
          </button>
        </div>
      ) : (
        <div
          className={[
            "mt-2 text-xs font-medium",
            status === "approved" ? "text-profit" : "text-loss",
          ].join(" ")}
        >
          {status === "approved"
            ? "Approved — submitted"
            : status === "failed"
              ? "Approved but not executed — see the reply below"
              : "Rejected by user"}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Message Bubble
// ---------------------------------------------------------------------------

interface MessageBubbleProps {
  message: ChatMessage;
  onApprove: (msg: ChatMessage) => void;
  onReject: (msgId: string) => void;
}

function MessageBubble({ message, onApprove, onReject }: MessageBubbleProps) {
  const isUser = message.role === "user";

  return (
    <div className={`flex gap-2 px-3 py-2 ${isUser ? "flex-row-reverse" : "flex-row"}`}>
      {/* Avatar */}
      <div
        className={[
          "w-5 h-5 rounded-full flex items-center justify-center shrink-0 mt-0.5",
          isUser
            ? "bg-accent/20 text-accent"
            : "bg-surface-hover text-text-secondary",
        ].join(" ")}
      >
        {isUser ? <User size={10} /> : <Bot size={10} />}
      </div>

      {/* Bubble */}
      <div
        className={[
          "max-w-[80%] flex flex-col gap-0.5",
          isUser ? "items-end" : "items-start",
        ].join(" ")}
      >
        {message.toolCall ? (
          <ToolCard
            toolCall={message.toolCall}
            status={message.toolStatus ?? "pending"}
            onApprove={() => onApprove(message)}
            onReject={() => onReject(message.id)}
          />
        ) : (
          <div
            className={[
              "px-2.5 py-1.5 rounded-lg text-xs leading-relaxed whitespace-pre-wrap",
              isUser
                ? "bg-accent/10 text-text-primary rounded-tr-none border border-accent/20"
                : "bg-surface-card text-text-primary rounded-tl-none border border-border-default",
            ].join(" ")}
          >
            {message.content}
          </div>
        )}
        <span className="text-xxs text-text-muted px-0.5">
          {fmtTime(message.timestamp)}
        </span>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main Widget
// ---------------------------------------------------------------------------

interface AIAdvisorWidgetProps {
  node?: unknown;
}

function AIAdvisorWidget({ node: _node }: AIAdvisorWidgetProps) {
  // ---------------------------------------------------------------------------
  // Shared conversation store (synced with AITutorPill)
  // ---------------------------------------------------------------------------
  const storeMessages = useAIConversationStore((s) => s.messages);
  const storeIsStreaming = useAIConversationStore((s) => s.isStreaming);
  const addMessage = useAIConversationStore((s) => s.addMessage);
  const setStreaming = useAIConversationStore((s) => s.setStreaming);
  const clearMessages = useAIConversationStore((s) => s.clearMessages);

  // ---------------------------------------------------------------------------
  // Local state for tool call augmentation — per-session, not persisted
  // toolMeta maps message id → { toolCall, toolStatus }
  // ---------------------------------------------------------------------------
  const [toolMeta, setToolMeta] = useState<Map<string, { toolCall?: ToolCall; toolStatus?: "pending" | "approved" | "rejected" | "failed" }>>(
    () => new Map(),
  );

  // Merge store messages with local tool meta for rendering
  const messages: ChatMessage[] = storeMessages.map((m) => {
    const meta = toolMeta.get(m.id);
    return { ...m, toolCall: meta?.toolCall, toolStatus: meta?.toolStatus };
  });

  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const inputRef = useRef<HTMLInputElement | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const configured = useIsAIConfigured();

  // On mount, check backend status to sync LLM config into settings store
  useEffect(() => {
    void fetchAdvisorStatus();
  }, []);

  // Auto-scroll to bottom whenever messages change
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [storeMessages]);

  const clearChat = useCallback(() => {
    clearMessages();
    setToolMeta(new Map());
    inputRef.current?.focus();
  }, [clearMessages]);

  const handleApprove = useCallback(
    async (msg: ChatMessage) => {
      if (!msg.toolCall) return;

      // Mark as approved in local tool meta
      setToolMeta((prev) => {
        const next = new Map(prev);
        next.set(msg.id, { ...prev.get(msg.id), toolCall: msg.toolCall, toolStatus: "approved" });
        return next;
      });

      const outcome = await executeApprovedToolCall(msg.toolCall);
      if (!outcome.executed) {
        // An approval that did not result in a submitted order must not keep
        // a green "Approved" card — the card state follows the real outcome.
        setToolMeta((prev) => {
          const next = new Map(prev);
          next.set(msg.id, { ...prev.get(msg.id), toolCall: msg.toolCall, toolStatus: "failed" });
          return next;
        });
      }
      addMessage("assistant", outcome.message);
    },
    [addMessage],
  );

  const handleReject = useCallback((msgId: string) => {
    setToolMeta((prev) => {
      const next = new Map(prev);
      const existing = prev.get(msgId);
      next.set(msgId, { ...existing, toolStatus: "rejected" });
      return next;
    });
    addMessage("assistant", "Order cancelled by user.");
  }, [addMessage]);

  const sendMessage = useCallback(async () => {
    const text = draft.trim();
    if (!text || sending) return;

    setDraft("");
    setSending(true);
    addMessage("user", text);

    // Build conversation payload from the store snapshot after adding the user message
    const snapshot = useAIConversationStore.getState().messages;
    const conversationPayload = snapshot.map((m) => ({ role: m.role, content: m.content }));

    const controller = new AbortController();
    abortRef.current = controller;

    // Add placeholder assistant message for streaming token updates
    const assistantId = generateId();
    useAIConversationStore.setState((state) => ({
      messages: [
        ...state.messages,
        {
          id: assistantId,
          role: "assistant" as const,
          content: "",
          timestamp: Date.now(),
          route: state.currentRoute,
        },
      ],
    }));
    setStreaming(true);

    let replyContent = "";

    try {
      replyContent = await streamAdvisorMessage(
        conversationPayload,
        (_token, fullText) => {
          useAIConversationStore.setState((state) => ({
            messages: state.messages.map((m) =>
              m.id === assistantId ? { ...m, content: fullText } : m,
            ),
          }));
        },
        controller.signal,
      );

      // Detect tool calls in the final reply and store in local meta
      const toolCall = parseToolCall(replyContent);
      if (toolCall) {
        setToolMeta((prev) => {
          const next = new Map(prev);
          next.set(assistantId, { toolCall, toolStatus: "pending" });
          return next;
        });
      }

      // Finalize content in store
      useAIConversationStore.setState((state) => ({
        messages: state.messages.map((m) =>
          m.id === assistantId ? { ...m, content: replyContent } : m,
        ),
      }));
    } catch (err: unknown) {
      const errMsg = err instanceof Error ? err.message : String(err);

      if (errMsg === "STREAMING_NOT_AVAILABLE") {
        // Remove empty placeholder, fall back to non-streaming
        useAIConversationStore.setState((state) => ({
          messages: state.messages.filter((m) => m.id !== assistantId),
        }));
        setStreaming(false);

        try {
          replyContent = await postAdvisorMessage(conversationPayload, controller.signal);
        } catch (fallbackErr: unknown) {
          const fallbackMsg = fallbackErr instanceof Error ? fallbackErr.message : String(fallbackErr);
          replyContent = `Error: ${fallbackMsg}`;
        }

        const toolCall = parseToolCall(replyContent);
        const newId = generateId();
        useAIConversationStore.setState((state) => ({
          messages: [
            ...state.messages,
            {
              id: newId,
              role: "assistant" as const,
              content: replyContent,
              timestamp: Date.now(),
              route: state.currentRoute,
            },
          ],
        }));
        if (toolCall) {
          setToolMeta((prev) => {
            const next = new Map(prev);
            next.set(newId, { toolCall, toolStatus: "pending" });
            return next;
          });
        }
      } else if (controller.signal.aborted) {
        // Component unmounted — do nothing
      } else {
        // Real error — replace empty placeholder with error text
        useAIConversationStore.setState((state) => ({
          messages: state.messages.map((m) =>
            m.id === assistantId ? { ...m, content: `Error: ${errMsg}` } : m,
          ),
        }));
      }
    } finally {
      setSending(false);
      setStreaming(false);
      abortRef.current = null;
      inputRef.current?.focus();
    }
  }, [draft, sending, addMessage, setStreaming]);

  const handleKeyDown = useCallback(
    (e: KeyboardEvent<HTMLInputElement>) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        void sendMessage();
      }
    },
    [sendMessage],
  );

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      abortRef.current?.abort();
    };
  }, []);

  const isEmpty = storeMessages.length === 0;

  return (
    <div className="h-full flex flex-col bg-surface-base text-text-primary overflow-hidden">

      {/* HEADER */}
      <div className="flex items-center gap-2 px-2 py-1 border-b border-border-default bg-surface-card shrink-0">
        <Bot size={11} className="text-text-muted shrink-0" />
        <span className="font-heading font-semibold text-sm text-text-secondary uppercase tracking-wider">
          AI Advisor
        </span>
        <div className="flex-1" />
        {messages.length > 0 && (
          <button
            type="button"
            onClick={clearChat}
            className="p-1 rounded text-text-muted hover:text-loss hover:bg-loss/10 transition-colors"
            aria-label="Clear chat"
            title="Clear chat history"
          >
            <Trash2 size={11} />
          </button>
        )}
        <span
          className={[
            "text-xxs font-medium px-1.5 py-0.5 rounded border",
            configured
              ? "text-profit bg-profit/10 border-profit/30"
              : "text-text-muted bg-surface-hover border-border-default",
          ].join(" ")}
        >
          {configured ? "Connected" : "Not configured"}
        </span>
      </div>

      {/* MESSAGE AREA */}
      {isEmpty ? (
        <div className="flex-1 flex flex-col items-center justify-center gap-3 px-4 text-center">
          {configured ? (
            <>
              <Bot size={28} className="text-text-muted" />
              <div>
                <p className="text-xs text-text-secondary">AI Advisor</p>
                <p className="text-xs text-text-muted mt-1 leading-relaxed max-w-52">
                  Ask me anything about trading, markets, or strategies.
                </p>
              </div>
            </>
          ) : (
            <>
              <Settings size={28} className="text-text-muted" />
              <div>
                <p className="text-xs text-text-secondary">LLM Not Configured</p>
                <p className="text-xs text-text-muted mt-1 leading-relaxed max-w-56">
                  Configure your LLM provider in Settings &rarr; AI to enable the AI trading advisor.
                </p>
              </div>
              <Button
                size="sm"
                variant="outline"
                className="h-6 text-xs px-2.5 border-border-default text-text-secondary hover:text-text-primary"
                onClick={() => {
                  window.dispatchEvent(new CustomEvent("flinttrade:navigate", { detail: "/settings" }));
                }}
              >
                Open Settings
              </Button>
            </>
          )}
        </div>
      ) : (
        <ScrollArea className="flex-1">
          <div
            ref={scrollRef}
            className="h-full overflow-auto"
          >
            <div className="py-1">
              {messages.map((msg) => (
                <MessageBubble
                  key={msg.id}
                  message={msg}
                  onApprove={(m) => void handleApprove(m)}
                  onReject={handleReject}
                />
              ))}
              {sending && !storeIsStreaming && (
                <div className="flex gap-2 px-3 py-2">
                  <div className="w-5 h-5 rounded-full bg-surface-hover flex items-center justify-center shrink-0 mt-0.5">
                    <Bot size={10} className="text-text-secondary" />
                  </div>
                  <div className="px-2.5 py-1.5 rounded-lg rounded-tl-none bg-surface-card border border-border-default flex items-center gap-1.5">
                    <Loader2 size={10} className="text-text-muted animate-spin" />
                    <span className="text-xs text-text-muted">Thinking...</span>
                  </div>
                </div>
              )}
            </div>
          </div>
        </ScrollArea>
      )}

      {/* COMPOSE BAR */}
      <div className="flex items-center gap-1.5 px-2 py-1.5 border-t border-border-default bg-surface-card shrink-0">
        <Input
          ref={inputRef}
          type="text"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={configured ? "Ask the AI advisor..." : "Configure LLM in Settings first..."}
          disabled={sending}
          className="h-10 flex-1 text-sm bg-surface-card border-border-default text-text-primary placeholder-text-muted rounded focus-visible:ring-1 focus-visible:ring-accent/50 disabled:opacity-60"
        />
        <Button
          size="sm"
          onClick={() => void sendMessage()}
          disabled={!draft.trim() || sending}
          className="bg-accent text-white rounded-md px-4 h-10 shrink-0 hover:bg-accent/90 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
          aria-label="Send message"
        >
          <Send size={14} />
        </Button>
      </div>
    </div>
  );
}

export default memo(AIAdvisorWidget);
