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
import { Send, Bot, User, Loader2, Settings, Trash2 } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { useSettingsStore } from "@/stores/settingsStore";
import { useAIConversationStore } from "@/stores/aiConversationStore";
import { getAdvisorBase } from "@/services/advisorApi";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const TOOL_CALL_PATTERN = /\[TOOL_CALL:([\s\S]*?)\]/;

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface ToolCall {
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
  toolStatus?: "pending" | "approved" | "rejected";
}

interface AdvisorResponse {
  status: "success" | "error";
  data?: { response: string };
  message?: string;
}

interface AdvisorStatusResponse {
  status: "success" | "error";
  data?: { configured: boolean; provider: string; model: string };
}

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
    const base = getAdvisorBase();
    const resp = await fetch(`${base}/api/v1/advisor/status`);
    if (!resp.ok) return;
    const json = (await resp.json()) as AdvisorStatusResponse;
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

  const json = (await resp.json()) as AdvisorResponse;

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
  status: "pending" | "approved" | "rejected";
  onApprove: () => void;
  onReject: () => void;
}

function ToolCard({ toolCall, status, onApprove, onReject }: ToolCardProps) {
  return (
    <div className="bg-surface-card border border-border-default rounded-lg p-3">
      <div className="text-xxs text-text-muted uppercase tracking-wider mb-1">
        AI wants to execute
      </div>
      <div className="font-mono text-sm font-bold text-text-primary">
        {toolCall.description}
      </div>
      {toolCall.endpoint && (
        <div className="font-mono text-xxs text-text-muted mt-1">
          {toolCall.method} {toolCall.endpoint}
        </div>
      )}
      {status === "pending" ? (
        <div className="flex gap-2 mt-3">
          <button
            type="button"
            onClick={onApprove}
            className="px-4 py-1.5 text-xs font-semibold rounded bg-profit/10 text-profit border border-profit/30 hover:bg-profit/20 transition-colors"
          >
            Approve
          </button>
          <button
            type="button"
            onClick={onReject}
            className="px-4 py-1.5 text-xs font-semibold rounded bg-loss/10 text-loss border border-loss/30 hover:bg-loss/20 transition-colors"
          >
            Reject
          </button>
        </div>
      ) : (
        <div
          className={[
            "mt-2 text-xs font-medium",
            status === "approved" ? "text-profit" : "text-loss",
          ].join(" ")}
        >
          {status === "approved" ? "Approved" : "Rejected by user"}
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
  const [toolMeta, setToolMeta] = useState<Map<string, { toolCall?: ToolCall; toolStatus?: "pending" | "approved" | "rejected" }>>(
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

      const base = getAdvisorBase();
      const endpoint = msg.toolCall.endpoint.startsWith("/")
        ? msg.toolCall.endpoint
        : `/api/v1/${msg.toolCall.endpoint}`;

      try {
        const resp = await fetch(`${base}${endpoint}`, {
          method: msg.toolCall.method || "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(msg.toolCall.payload),
        });
        const json = (await resp.json()) as Record<string, unknown>;
        addMessage(
          "assistant",
          `Action executed successfully.\n\n\`\`\`json\n${JSON.stringify(json, null, 2)}\n\`\`\``,
        );
      } catch (err: unknown) {
        const errText = err instanceof Error ? err.message : String(err);
        addMessage("assistant", `Action failed: ${errText}`);
      }
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
