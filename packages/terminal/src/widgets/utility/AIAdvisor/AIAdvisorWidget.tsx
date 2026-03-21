/**
 * AIAdvisorWidget — chat interface for the FlintTrade AI trading advisor.
 *
 * Wired to the FlintTrade Python backend at /ft-api/api/v1/advisor.
 * Features:
 *   - Conversation memory: full message history sent on each request
 *   - localStorage persistence (flinttrade:chat-history)
 *   - SSE streaming responses with token-by-token rendering
 *   - Fallback to non-streaming endpoint on 404
 *   - MCP tool confirmation cards (Approve / Reject)
 *   - Clear chat button
 *   - "Not configured" state with guidance to Settings when LLM provider is unset
 *   - Checks advisor/status on mount to sync LLM config state
 */

import { useState, useRef, useEffect, useCallback, type KeyboardEvent } from "react";
import { Send, Bot, User, Loader2, Settings, Trash2 } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { useSettingsStore } from "@/stores/settingsStore";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const STORAGE_KEY = "flinttrade:chat-history";
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

function getApiBase(): string {
  return import.meta.env.DEV ? "/ft-api" : "";
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
      try {
        payload = parts[3] ? (JSON.parse(parts[3]) as Record<string, unknown>) : {};
      } catch {
        // Invalid JSON in payload — ignore
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
  try {
    const jsonMatch = /\{[\s\S]*"type"\s*:\s*"tool_call"[\s\S]*\}/.exec(content);
    if (jsonMatch) {
      const parsed = JSON.parse(jsonMatch[0]) as Record<string, unknown>;
      if (parsed.type === "tool_call") {
        return {
          description: (parsed.description as string) ?? "Execute action",
          endpoint: (parsed.endpoint as string) ?? "",
          method: ((parsed.method as string) ?? "POST").toUpperCase(),
          payload: (parsed.payload as Record<string, unknown>) ?? {},
        };
      }
    }
  } catch {
    // Not valid JSON — ignore
  }

  return undefined;
}

/**
 * Load chat messages from localStorage.
 */
function loadMessages(): ChatMessage[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw) as ChatMessage[];
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

/**
 * Save chat messages to localStorage.
 */
function saveMessages(messages: ChatMessage[]): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(messages));
  } catch {
    // Storage full or unavailable — silently ignore
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
    const base = getApiBase();
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
  const base = getApiBase();
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
      for (const line of chunk.split("\n")) {
        if (!line.startsWith("data: ")) continue;
        const raw = line.slice(6).trim();
        if (!raw || raw === "[DONE]") continue;
        try {
          const data = JSON.parse(raw) as { done?: boolean; token?: string };
          if (data.done) break;
          if (data.token) {
            assistantText += data.token;
            onToken(data.token, assistantText);
          }
        } catch {
          // Malformed SSE line — skip
        }
      }
    }
  } finally {
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
  const base = getApiBase();
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

export default function AIAdvisorWidget({ node: _node }: AIAdvisorWidgetProps) {
  const [messages, setMessages] = useState<ChatMessage[]>(loadMessages);
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);
  const [streaming, setStreaming] = useState(false);
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const inputRef = useRef<HTMLInputElement | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const configured = useIsAIConfigured();

  // On mount, check backend status to sync LLM config into settings store
  useEffect(() => {
    void fetchAdvisorStatus();
  }, []);

  // Persist messages to localStorage whenever they change
  useEffect(() => {
    saveMessages(messages);
  }, [messages]);

  // Auto-scroll to bottom whenever messages change
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages]);

  const clearChat = useCallback(() => {
    setMessages([]);
    localStorage.removeItem(STORAGE_KEY);
    inputRef.current?.focus();
  }, []);

  const handleApprove = useCallback(
    async (msg: ChatMessage) => {
      if (!msg.toolCall) return;

      // Mark as approved
      setMessages((prev) =>
        prev.map((m) => (m.id === msg.id ? { ...m, toolStatus: "approved" as const } : m)),
      );

      const base = getApiBase();
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
        const resultMsg: ChatMessage = {
          id: generateId(),
          role: "assistant",
          content: `Action executed successfully.\n\n\`\`\`json\n${JSON.stringify(json, null, 2)}\n\`\`\``,
          timestamp: Date.now(),
        };
        setMessages((prev) => [...prev, resultMsg]);
      } catch (err: unknown) {
        const errText = err instanceof Error ? err.message : String(err);
        const errorMsg: ChatMessage = {
          id: generateId(),
          role: "assistant",
          content: `Action failed: ${errText}`,
          timestamp: Date.now(),
        };
        setMessages((prev) => [...prev, errorMsg]);
      }
    },
    [],
  );

  const handleReject = useCallback((msgId: string) => {
    setMessages((prev) =>
      prev.map((m) => (m.id === msgId ? { ...m, toolStatus: "rejected" as const } : m)),
    );

    const rejectMsg: ChatMessage = {
      id: generateId(),
      role: "assistant",
      content: "Order cancelled by user.",
      timestamp: Date.now(),
    };
    setMessages((prev) => [...prev, rejectMsg]);
  }, []);

  const sendMessage = useCallback(async () => {
    const text = draft.trim();
    if (!text || sending) return;

    const userMsg: ChatMessage = {
      id: generateId(),
      role: "user",
      content: text,
      timestamp: Date.now(),
    };

    const updatedMessages = [...messages, userMsg];
    setMessages(updatedMessages);
    setDraft("");
    setSending(true);

    // Prepare conversation payload
    const conversationPayload = updatedMessages.map((m) => ({
      role: m.role,
      content: m.content,
    }));

    const controller = new AbortController();
    abortRef.current = controller;

    let replyContent = "";

    // Try streaming first, fallback to non-streaming
    try {
      // Create placeholder assistant message for streaming
      const assistantId = generateId();
      const placeholderMsg: ChatMessage = {
        id: assistantId,
        role: "assistant",
        content: "",
        timestamp: Date.now(),
      };
      setMessages((prev) => [...prev, placeholderMsg]);
      setStreaming(true);

      replyContent = await streamAdvisorMessage(
        conversationPayload,
        (_token, fullText) => {
          setMessages((prev) =>
            prev.map((m) => (m.id === assistantId ? { ...m, content: fullText } : m)),
          );
        },
        controller.signal,
      );

      // Final update with complete text
      const toolCall = parseToolCall(replyContent);
      setMessages((prev) =>
        prev.map((m) =>
          m.id === assistantId
            ? {
                ...m,
                content: replyContent,
                toolCall,
                toolStatus: toolCall ? ("pending" as const) : undefined,
              }
            : m,
        ),
      );
    } catch (err: unknown) {
      const errMsg = err instanceof Error ? err.message : String(err);

      if (errMsg === "STREAMING_NOT_AVAILABLE") {
        // Fallback: remove the streaming placeholder, use non-streaming
        setMessages(updatedMessages); // reset to before placeholder
        setStreaming(false);

        try {
          replyContent = await postAdvisorMessage(conversationPayload, controller.signal);
        } catch (fallbackErr: unknown) {
          const fallbackMsg = fallbackErr instanceof Error ? fallbackErr.message : String(fallbackErr);
          replyContent = `Error: ${fallbackMsg}`;
        }

        const toolCall = parseToolCall(replyContent);
        const assistantMsg: ChatMessage = {
          id: generateId(),
          role: "assistant",
          content: replyContent,
          timestamp: Date.now(),
          toolCall,
          toolStatus: toolCall ? "pending" : undefined,
        };
        setMessages((prev) => [...prev, assistantMsg]);
      } else if (controller.signal.aborted) {
        // User navigated away or component unmounted — do nothing
      } else {
        // Stream failed with a real error — show it
        // Remove the empty placeholder and add error message
        setMessages((prev) => {
          const filtered = prev.filter((m) => m.content !== "" || m.role !== "assistant");
          return [
            ...filtered,
            {
              id: generateId(),
              role: "assistant" as const,
              content: `Error: ${errMsg}`,
              timestamp: Date.now(),
            },
          ];
        });
      }
    } finally {
      setSending(false);
      setStreaming(false);
      abortRef.current = null;
      inputRef.current?.focus();
    }
  }, [draft, sending, messages]);

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

  const isEmpty = messages.length === 0;

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
              {sending && !streaming && (
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
