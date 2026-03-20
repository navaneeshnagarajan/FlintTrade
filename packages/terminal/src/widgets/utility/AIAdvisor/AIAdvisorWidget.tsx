/**
 * AIAdvisorWidget — chat interface for the FlintTrade AI trading advisor.
 *
 * Wired to the FlintTrade Python backend at /ft-api/api/v1/advisor.
 * Features:
 *   - Message thread with user/assistant bubbles
 *   - Input + send button (keyboard: Enter to send, Shift+Enter for newline)
 *   - Local message history via useState
 *   - Loading spinner while waiting for LLM response
 *   - "Not configured" state with guidance to Settings when LLM provider is unset
 *   - Checks advisor/status on mount to sync LLM config state
 */

import { useState, useRef, useEffect, useCallback, type KeyboardEvent } from "react";
import { MessageSquare, Send, Bot, User, Loader2, Settings } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { useSettingsStore } from "@/stores/settingsStore";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  timestamp: number;
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

function fmtTime(ts: number): string {
  return new Date(ts).toLocaleTimeString("en-IN", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

/**
 * Check if the LLM provider is configured in the settings store.
 * Updated on mount by querying the backend status endpoint.
 */
function useIsAIConfigured(): boolean {
  return useSettingsStore((s) => s.llm.provider.length > 0);
}

/**
 * POST a message to the advisor backend and return the response text.
 * Throws on network or server errors.
 */
async function postAdvisorMessage(
  message: string,
  context: string,
): Promise<string> {
  const base = import.meta.env.DEV ? "/ft-api" : "";
  const resp = await fetch(`${base}/api/v1/advisor`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message, context }),
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

/**
 * Fetch advisor status from the backend and sync LLM config into the settings store.
 */
async function fetchAdvisorStatus(): Promise<void> {
  try {
    const base = import.meta.env.DEV ? "/ft-api" : "";
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

// ---------------------------------------------------------------------------
// Message bubble
// ---------------------------------------------------------------------------

interface MessageBubbleProps {
  message: ChatMessage;
}

function MessageBubble({ message }: MessageBubbleProps) {
  const isUser = message.role === "user";

  return (
    <div className={`flex gap-2 px-3 py-2 ${isUser ? "flex-row-reverse" : "flex-row"}`}>
      {/* Avatar */}
      <div
        className={[
          "w-5 h-5 rounded-full flex items-center justify-center shrink-0 mt-0.5",
          isUser
            ? "bg-primary/20 text-primary"
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
        <div
          className={[
            "px-2.5 py-1.5 rounded-lg text-xs leading-relaxed whitespace-pre-wrap",
            isUser
              ? "bg-primary/15 text-text-primary rounded-tr-none border border-primary/20"
              : "bg-surface-card text-text-primary rounded-tl-none border border-border-default",
          ].join(" ")}
        >
          {message.content}
        </div>
        <span className="text-xxs text-text-muted px-0.5">
          {fmtTime(message.timestamp)}
        </span>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main widget
// ---------------------------------------------------------------------------

interface AIAdvisorWidgetProps {
  node?: unknown;
}

export default function AIAdvisorWidget({ node: _node }: AIAdvisorWidgetProps) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const inputRef = useRef<HTMLInputElement | null>(null);
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
  }, [messages]);

  const sendMessage = useCallback(async () => {
    const text = draft.trim();
    if (!text || sending) return;

    const userMsg: ChatMessage = {
      role: "user",
      content: text,
      timestamp: Date.now(),
    };

    setMessages((prev) => [...prev, userMsg]);
    setDraft("");
    setSending(true);

    let replyContent: string;
    try {
      replyContent = await postAdvisorMessage(text, "");
    } catch (err: unknown) {
      const errMsg = err instanceof Error ? err.message : String(err);
      replyContent = `Error: ${errMsg}`;
    }

    const assistantMsg: ChatMessage = {
      role: "assistant",
      content: replyContent,
      timestamp: Date.now(),
    };

    setMessages((prev) => [...prev, assistantMsg]);
    setSending(false);
    inputRef.current?.focus();
  }, [draft, sending]);

  const handleKeyDown = useCallback(
    (e: KeyboardEvent<HTMLInputElement>) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        void sendMessage();
      }
    },
    [sendMessage],
  );

  const isEmpty = messages.length === 0;

  return (
    <div className="h-full flex flex-col bg-surface-base text-text-primary overflow-hidden">

      {/* HEADER */}
      <div className="flex items-center gap-2 px-2 py-1 border-b border-border-default bg-surface-card shrink-0">
        <Bot size={11} className="text-text-muted shrink-0" />
        <span className="text-xs font-semibold text-text-secondary uppercase tracking-wider">
          AI Advisor
        </span>
        <div className="flex-1" />
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
              <MessageSquare size={28} className="text-text-muted" />
              <div>
                <p className="text-xs text-text-secondary">AI Advisor</p>
                <p className="text-xs text-text-muted mt-1 leading-relaxed max-w-52">
                  Ask about market analysis, options strategies, technical indicators, or portfolio management.
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
                  // Navigate to settings — dispatch a custom event that the shell can listen to
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
          {/* Expose the viewport div for auto-scroll */}
          <div
            ref={scrollRef}
            className="h-full overflow-auto"
          >
            <div className="py-1">
              {messages.map((msg, idx) => (
                <MessageBubble
                  key={`${msg.role}-${msg.timestamp}-${idx}`}
                  message={msg}
                />
              ))}
              {sending && (
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
          className="h-7 flex-1 text-xs bg-surface-hover border-border-default text-text-primary placeholder-text-muted rounded focus-visible:ring-1 focus-visible:ring-primary/50 disabled:opacity-60"
        />
        <Button
          size="sm"
          onClick={() => void sendMessage()}
          disabled={!draft.trim() || sending}
          className="h-7 w-7 p-0 shrink-0 bg-primary/20 hover:bg-primary/30 text-primary border border-primary/30 rounded disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
          aria-label="Send message"
        >
          <Send size={11} />
        </Button>
      </div>
    </div>
  );
}
