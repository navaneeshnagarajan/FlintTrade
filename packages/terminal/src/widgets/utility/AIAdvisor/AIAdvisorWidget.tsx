/**
 * AIAdvisorWidget — chat interface for the FlintTrade AI trading advisor.
 *
 * UI structure ready to wire to LLM backend once configured in Settings.
 * Features:
 *   - Message thread with user/assistant bubbles
 *   - Input + send button (keyboard: Enter to send, Shift+Enter for newline)
 *   - Local message history via useState
 *   - Empty state with configuration guidance
 *   - Graceful "not configured" stub response when backend is absent
 */

import { useState, useRef, useEffect, useCallback, KeyboardEvent } from "react";
import { MessageSquare, Send, Bot, User } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  timestamp: number;
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

/** Shown when the LLM backend is not yet configured. */
const NOT_CONFIGURED_REPLY =
  "AI advisor not configured. Go to Settings → AI/LLM to set up.";

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
 * Stub — returns false until the LLM bridge is implemented.
 * Replace with a real check (env var / settings atom) once wired.
 */
function isAIConfigured(): boolean {
  return false;
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
            "px-2.5 py-1.5 rounded-lg text-xs leading-relaxed",
            isUser
              ? "bg-primary/15 text-text-primary rounded-tr-none border border-primary/20"
              : "bg-surface-card text-text-primary rounded-tl-none border border-border-default",
          ].join(" ")}
        >
          {message.content}
        </div>
        <span className="text-[9px] text-text-muted px-0.5">
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

    // Simulate async reply — replace with real LLM call when backend is wired
    await new Promise<void>((resolve) => setTimeout(resolve, 200));

    const replyContent = isAIConfigured()
      ? "LLM backend response would appear here."
      : NOT_CONFIGURED_REPLY;

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
        <span className="text-[10px] font-semibold text-text-secondary uppercase tracking-wider">
          AI Advisor
        </span>
        <div className="flex-1" />
        <span
          className={[
            "text-[9px] font-medium px-1.5 py-0.5 rounded border",
            isAIConfigured()
              ? "text-profit bg-profit/10 border-profit/30"
              : "text-text-muted bg-surface-hover border-border-default",
          ].join(" ")}
        >
          {isAIConfigured() ? "Connected" : "Not configured"}
        </span>
      </div>

      {/* MESSAGE AREA */}
      {isEmpty ? (
        <div className="flex-1 flex flex-col items-center justify-center gap-3 px-4 text-center">
          <MessageSquare size={28} className="text-text-muted" />
          <div>
            <p className="text-xs text-text-secondary">AI Advisor</p>
            <p className="text-[10px] text-text-muted mt-1 leading-relaxed max-w-52">
              Configure LLM in Settings to enable AI trading advisor
            </p>
          </div>
          <p className="text-[9px] text-text-muted">
            You can still send messages — they will queue until configured.
          </p>
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
                  <div className="px-2.5 py-1.5 rounded-lg rounded-tl-none bg-surface-card border border-border-default">
                    <span className="text-[10px] text-text-muted tracking-widest">...</span>
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
          placeholder="Ask the AI advisor..."
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
