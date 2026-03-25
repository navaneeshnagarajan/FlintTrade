/**
 * AITutorPill.tsx
 *
 * Floating AI tutor assistant pinned to the bottom-right corner of every route.
 *
 * States:
 *   - Minimized: small pill with sparkle icon + "Ask AI" label, subtle hover glow.
 *   - Expanded:  compact chat panel (300px wide, 400px tall) — GlassCard surface
 *                with header, scrollable message list, input field, and footer.
 *
 * Behaviour:
 *   - Only renders when skillStore.helpPrefs.aiTutor === true.
 *   - Reads/writes to aiConversationStore (shared with /ai route and AIAdvisorWidget).
 *   - Context-aware: reads the current route via useLocation() and passes it
 *     as context on every API request so responses are route-aware.
 *   - Minimized by default; expands/collapses on click.
 *   - Escape key collapses the panel.
 *   - Hidden on small screens (< sm breakpoint) to avoid obscuring content.
 *   - SSE streaming from /ft-api/api/v1/advisor/stream with non-streaming fallback.
 *
 * Animation:
 *   - Pill uses scale + opacity spring for hover glow.
 *   - Panel expands with scale + height (origin: bottom-right).
 *   - AnimatePresence handles mount/unmount transitions.
 *   - Typing indicator animates when isStreaming is true.
 *   - Respects prefers-reduced-motion.
 *
 * Accessibility:
 *   - role="dialog" on expanded panel with aria-label.
 *   - Pill button has descriptive aria-label.
 *   - Focus moves to input when panel opens.
 *   - Escape closes panel (keyboard trap-free — focus returns to trigger).
 */

import { useState, useRef, useEffect, useCallback, KeyboardEvent } from "react";
import { useLocation } from "react-router-dom";
import { AnimatePresence, motion } from "framer-motion";
import { Sparkles, X, Send, Bot, Settings } from "lucide-react";
import { useShallow } from "zustand/react/shallow";
import { GlassCard } from "@/components/ui/GlassCard";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import { useSkillStore } from "@/stores/skillStore";
import { useAIConversationStore } from "@/stores/aiConversationStore";
import { useSettingsStore } from "@/stores/settingsStore";
import { motionConfig, EASE_ENTER, EASE_EXIT, DURATION } from "@/lib/motion";
import { cn } from "@/lib/utils";
import { getAdvisorBase } from "@/services/advisorApi";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

/** Maximum number of messages visible in the pill panel (scroll for older) */
const VISIBLE_MESSAGE_COUNT = 50;

// ---------------------------------------------------------------------------
// API helpers
// ---------------------------------------------------------------------------

interface AdvisorStatusResponse {
  status: "success" | "error";
  data?: { configured: boolean; provider: string; model: string };
}

interface AdvisorResponse {
  status: "success" | "error";
  data?: { response: string };
  message?: string;
}

/**
 * Fetch advisor status from the backend and sync LLM settings into the store.
 * Silently no-ops if the backend is not running.
 */
async function fetchAdvisorStatus(): Promise<void> {
  try {
    const resp = await fetch(`${getAdvisorBase()}/api/v1/advisor/status`);
    if (!resp.ok) return;
    const json = (await resp.json()) as AdvisorStatusResponse;
    if (json.status === "success" && json.data) {
      useSettingsStore.getState().setLLM({
        provider: json.data.provider,
        model: json.data.model,
      });
    }
  } catch {
    // Backend not running — leave settings as-is
  }
}

/**
 * POST conversation history to the SSE streaming endpoint.
 * Calls onToken for each incremental chunk. Returns the full assembled text.
 * Throws "STREAMING_NOT_AVAILABLE" (string) on 404 so the caller can fall back.
 */
async function streamAdvisorMessage(
  messages: Array<{ role: string; content: string }>,
  route: string,
  onToken: (token: string, fullText: string) => void,
  signal?: AbortSignal,
  activeWidget?: string | null,
): Promise<string> {
  const resp = await fetch(`${getAdvisorBase()}/api/v1/advisor/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ messages, context: { route, activeWidget: activeWidget ?? null } }),
    signal,
  });

  if (resp.status === 404) {
    throw new Error("STREAMING_NOT_AVAILABLE");
  }

  if (!resp.ok) {
    throw new Error(`Advisor API: HTTP ${resp.status}`);
  }

  const reader = resp.body?.getReader();
  if (!reader) throw new Error("No readable stream in response");

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
        try {
          const data = JSON.parse(raw) as { done?: boolean; token?: string };
          if (data.done) { streamDone = true; break; }
          if (data.token) {
            assistantText += data.token;
            onToken(data.token, assistantText);
          }
        } catch {
          // Malformed SSE line — skip
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
 * POST conversation history to the non-streaming advisor endpoint.
 * Used as fallback when streaming returns 404.
 */
async function postAdvisorMessage(
  messages: Array<{ role: string; content: string }>,
  route: string,
  signal?: AbortSignal,
  activeWidget?: string | null,
): Promise<string> {
  const resp = await fetch(`${getAdvisorBase()}/api/v1/advisor`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      messages,
      message: messages[messages.length - 1]?.content ?? "",
      context: { route, activeWidget: activeWidget ?? null },
    }),
    signal,
  });

  if (!resp.ok) throw new Error(`Advisor API: HTTP ${resp.status}`);

  const json = (await resp.json()) as AdvisorResponse;
  if (json.status === "error") return json.message ?? "Unknown error from advisor.";
  return json.data?.response ?? "No response from advisor.";
}

// ---------------------------------------------------------------------------
// Route label helper — returns a human-readable context string
// ---------------------------------------------------------------------------

function routeLabel(pathname: string): string {
  const segment = pathname.split("/")[1] ?? "";
  const labels: Record<string, string> = {
    "": "Home",
    welcome: "Welcome",
    explore: "Explore",
    setup: "Setup",
    settings: "Settings",
    trade: "Trade",
    invest: "Invest",
    learn: "Learn",
    lab: "Lab",
    automate: "Automate",
    ai: "AI Center",
  };
  return labels[segment] ?? segment.charAt(0).toUpperCase() + segment.slice(1);
}

// ---------------------------------------------------------------------------
// useActiveWidgetContext — subscribes to Dockview panel focus events
// ---------------------------------------------------------------------------

/**
 * Returns the id of the currently focused Dockview panel, or null.
 * Listens for "flinttrade:active-widget" CustomEvents dispatched from
 * TerminalRoute's onDockviewReady / onDidActivePanelChange handler.
 */
function useActiveWidgetContext(): string | null {
  const [activeWidget, setActiveWidget] = useState<string | null>(null);

  useEffect(() => {
    const handler = (e: Event) => {
      const detail = (e as CustomEvent<string>).detail;
      setActiveWidget(detail ?? null);
    };
    window.addEventListener("flinttrade:active-widget", handler);
    return () => window.removeEventListener("flinttrade:active-widget", handler);
  }, []);

  return activeWidget;
}

// ---------------------------------------------------------------------------
// TypingIndicator — three animated dots shown while isStreaming
// ---------------------------------------------------------------------------

function TypingIndicator() {
  const reduced = motionConfig.prefersReducedMotion();
  return (
    <div className="flex items-center gap-1 px-3 py-2" aria-label="AI is typing">
      {[0, 1, 2].map((i) => (
        <motion.span
          key={i}
          className="w-1.5 h-1.5 rounded-full bg-accent"
          animate={reduced ? {} : { opacity: [0.3, 1, 0.3], y: [0, -3, 0] }}
          transition={
            reduced
              ? { duration: 0 }
              : {
                  duration: 0.9,
                  repeat: Infinity,
                  delay: i * 0.18,
                  ease: "easeInOut",
                }
          }
        />
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// MessageBubble
// ---------------------------------------------------------------------------

interface MessageBubbleProps {
  role: "user" | "assistant";
  content: string;
  index: number;
}

function MessageBubble({ role, content, index }: MessageBubbleProps) {
  const reduced = motionConfig.prefersReducedMotion();
  const isUser = role === "user";

  return (
    <motion.div
      className={cn("flex", isUser ? "justify-end" : "justify-start")}
      initial={reduced ? { opacity: 0 } : { opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={motionConfig.stagger(index, { duration: DURATION.normal, ease: EASE_ENTER }, 0.03)}
    >
      <div
        className={cn(
          "max-w-[85%] rounded-2xl px-3 py-2 text-xs leading-relaxed",
          isUser
            ? "bg-accent text-white rounded-br-sm"
            : [
                "bg-surface-base border border-border-default text-text-secondary",
                "rounded-bl-sm",
                // Subtle glass shimmer on assistant bubbles
                "backdrop-blur-sm",
              ].join(" "),
        )}
        style={
          !isUser
            ? {
                background: "linear-gradient(135deg, rgba(22,22,31,0.9) 0%, rgba(26,26,40,0.85) 100%)",
              }
            : undefined
        }
      >
        {content}
      </div>
    </motion.div>
  );
}

// ---------------------------------------------------------------------------
// Pill (minimized state)
// ---------------------------------------------------------------------------

interface PillProps {
  onClick: () => void;
}

function Pill({ onClick }: PillProps) {
  const reduced = motionConfig.prefersReducedMotion();

  return (
    <motion.button
      type="button"
      onClick={onClick}
      aria-label="Open AI Tutor"
      aria-expanded={false}
      aria-controls="ai-tutor-panel"
      className={cn(
        "flex items-center gap-2 px-4 py-2.5 rounded-full",
        "bg-surface-card border border-border-default",
        "text-text-secondary text-xs font-medium",
        "shadow-lg cursor-pointer select-none",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent",
        "transition-colors duration-150 hover:border-accent/50 hover:text-text-primary",
      )}
      whileHover={
        reduced
          ? {}
          : {
              scale: 1.04,
              boxShadow: "0 0 0 1px rgba(var(--color-accent-rgb, 99,102,241), 0.35), 0 4px 20px rgba(0,0,0,0.4)",
            }
      }
      whileTap={reduced ? {} : { scale: 0.97 }}
      transition={{ duration: DURATION.fast, ease: EASE_ENTER }}
    >
      {/* Shimmer sparkle icon */}
      <motion.span
        animate={
          reduced
            ? {}
            : {
                rotate: [0, 15, -10, 0],
                scale: [1, 1.15, 1],
              }
        }
        transition={
          reduced
            ? { duration: 0 }
            : {
                duration: 2.5,
                repeat: Infinity,
                repeatDelay: 3,
                ease: "easeInOut",
              }
        }
        className="text-accent"
      >
        <Sparkles className="w-3.5 h-3.5" />
      </motion.span>
      <span>Ask AI</span>
    </motion.button>
  );
}

// ---------------------------------------------------------------------------
// Expanded panel
// ---------------------------------------------------------------------------

interface ExpandedPanelProps {
  onClose: () => void;
  routeName: string;
  currentRoute: string;
  isConfigured: boolean;
  activeWidget: string | null;
}

function ExpandedPanel({ onClose, routeName, currentRoute, isConfigured, activeWidget }: ExpandedPanelProps) {
  const inputRef = useRef<HTMLInputElement | null>(null);
  const scrollEndRef = useRef<HTMLDivElement | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const [inputValue, setInputValue] = useState("");
  // Tracks the id of the streaming placeholder so we can update it in-place
  const streamingIdRef = useRef<string | null>(null);

  const { messages, isStreaming, addMessage, setStreaming } = useAIConversationStore(
    useShallow((state) => ({
      messages: state.messages,
      isStreaming: state.isStreaming,
      addMessage: state.addMessage,
      setStreaming: state.setStreaming,
    })),
  );

  // We also need the low-level setState for in-place streaming updates.
  // Grab the store instance directly for the partial-update pattern.
  const updateMessageContent = useCallback((id: string, content: string) => {
    useAIConversationStore.setState((state) => ({
      messages: state.messages.map((m) =>
        m.id === id ? { ...m, content } : m,
      ),
    }));
  }, []);

  // Focus input when panel mounts
  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  // Close on Escape
  useEffect(() => {
    function handleKey(e: globalThis.KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    document.addEventListener("keydown", handleKey);
    return () => document.removeEventListener("keydown", handleKey);
  }, [onClose]);

  // Auto-scroll to latest message
  useEffect(() => {
    scrollEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, isStreaming]);

  // Abort in-flight request on unmount
  useEffect(() => {
    return () => {
      abortRef.current?.abort();
    };
  }, []);

  const handleSend = useCallback(async () => {
    const text = inputValue.trim();
    if (!text || isStreaming) return;

    setInputValue("");
    addMessage("user", text);
    setStreaming(true);

    // Build the conversation payload from the current store snapshot + the new user message
    const snapshot = useAIConversationStore.getState().messages;
    const conversationPayload = snapshot.map((m) => ({ role: m.role, content: m.content }));

    const controller = new AbortController();
    abortRef.current = controller;

    // Add a placeholder assistant message that will be filled by streaming tokens
    const placeholderId = `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 7)}`;
    streamingIdRef.current = placeholderId;
    useAIConversationStore.setState((state) => ({
      messages: [
        ...state.messages,
        {
          id: placeholderId,
          role: "assistant" as const,
          content: "",
          timestamp: Date.now(),
          route: currentRoute,
        },
      ],
    }));

    try {
      await streamAdvisorMessage(
        conversationPayload,
        currentRoute,
        (_token, fullText) => {
          updateMessageContent(placeholderId, fullText);
        },
        controller.signal,
        activeWidget,
      );
    } catch (err: unknown) {
      const errMsg = err instanceof Error ? err.message : String(err);

      if (errMsg === "STREAMING_NOT_AVAILABLE") {
        // Remove the empty placeholder, then call the non-streaming fallback
        useAIConversationStore.setState((state) => ({
          messages: state.messages.filter((m) => m.id !== placeholderId),
        }));

        try {
          const reply = await postAdvisorMessage(
            conversationPayload,
            currentRoute,
            controller.signal,
            activeWidget,
          );
          addMessage("assistant", reply);
        } catch (fallbackErr: unknown) {
          const msg = fallbackErr instanceof Error ? fallbackErr.message : String(fallbackErr);
          addMessage("assistant", `Error: ${msg}`);
        }
      } else if (!controller.signal.aborted) {
        // Real streaming error — replace empty placeholder with error text
        updateMessageContent(placeholderId, `Error: ${errMsg}`);
      }
      // If aborted the component is unmounting — do nothing
    } finally {
      streamingIdRef.current = null;
      abortRef.current = null;
      setStreaming(false);
      inputRef.current?.focus();
    }
  }, [inputValue, isStreaming, addMessage, setStreaming, currentRoute, updateMessageContent, activeWidget]);

  const handleKeyDown = useCallback((e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      void handleSend();
    }
  }, [handleSend]);

  const visibleMessages = messages.slice(-VISIBLE_MESSAGE_COUNT);
  const reduced = motionConfig.prefersReducedMotion();

  return (
    <motion.div
      id="ai-tutor-panel"
      role="dialog"
      aria-label="AI Tutor"
      aria-modal="false"
      className="w-[300px] overflow-hidden rounded-2xl shadow-2xl"
      initial={
        reduced ? { opacity: 0 } : { opacity: 0, scale: 0.9, y: 10 }
      }
      animate={{ opacity: 1, scale: 1, y: 0 }}
      exit={
        reduced ? { opacity: 0 } : { opacity: 0, scale: 0.88, y: 8 }
      }
      transition={{ duration: DURATION.normal, ease: EASE_ENTER }}
      style={{ transformOrigin: "bottom right" }}
    >
      <GlassCard glass className="flex flex-col gap-0 p-0 h-[400px]">
        {/* Header */}
        <div className="flex items-center gap-2.5 px-3.5 py-2.5 border-b border-border-default shrink-0">
          <div className="flex items-center gap-2 flex-1 min-w-0">
            <Bot className="w-3.5 h-3.5 text-accent shrink-0" />
            <span className="font-heading font-semibold text-xs text-text-primary truncate">
              AI Tutor
            </span>
            {/* Route context badge */}
            <span className="text-xs text-text-muted bg-surface-base border border-border-default rounded-full px-2 py-0.5 font-mono truncate shrink-0">
              {activeWidget ? activeWidget : routeName}
            </span>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Minimize AI Tutor"
            className="h-6 w-6 flex items-center justify-center rounded-full text-text-muted hover:text-text-primary hover:bg-surface-hover transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent shrink-0"
          >
            <X className="w-3 h-3" />
          </button>
        </div>

        {/* Messages */}
        <ScrollArea className="flex-1 min-h-0">
          <div className="px-3 py-3 space-y-2.5">
            {visibleMessages.length === 0 && (
              isConfigured ? (
                <div className="flex flex-col items-center justify-center py-8 gap-2 text-center">
                  <Sparkles className="w-5 h-5 text-accent/60" />
                  <p className="text-xs text-text-muted leading-relaxed">
                    Ask me anything about trading, indicators, or how to use FlintTrade.
                  </p>
                </div>
              ) : (
                <div className="flex flex-col items-center justify-center py-8 gap-2 text-center">
                  <Settings className="w-5 h-5 text-text-muted/60" />
                  <p className="text-xs text-text-muted leading-relaxed">
                    LLM not configured.
                  </p>
                  <p className="text-[10px] text-text-muted/60 leading-relaxed">
                    Open Settings &rarr; AI to set up your provider.
                  </p>
                </div>
              )
            )}
            {visibleMessages.map((msg, idx) => (
              <MessageBubble
                key={msg.id}
                role={msg.role}
                content={msg.content}
                index={idx}
              />
            ))}
            {isStreaming && <TypingIndicator />}
            <div ref={scrollEndRef} />
          </div>
        </ScrollArea>

        {/* Input row */}
        <div className="px-3 py-2.5 border-t border-border-default shrink-0">
          <div className="flex items-center gap-2">
            <Input
              ref={inputRef}
              value={inputValue}
              onChange={(e) => setInputValue(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder={isConfigured ? "Ask the AI tutor..." : "Configure LLM in Settings first..."}
              disabled={isStreaming || !isConfigured}
              className={cn(
                "bg-surface-base border-border-default text-text-primary text-xs h-8",
                "placeholder:text-text-muted focus-visible:ring-accent/50",
              )}
              aria-label="Message input"
            />
            <Button
              type="button"
              size="icon"
              onClick={() => void handleSend()}
              disabled={!inputValue.trim() || isStreaming || !isConfigured}
              aria-label="Send message"
              className="h-8 w-8 shrink-0 bg-accent hover:bg-accent/90 disabled:opacity-40"
            >
              <Send className="w-3 h-3" />
            </Button>
          </div>
        </div>

        {/* Footer */}
        <div className="px-3.5 py-1.5 border-t border-border-default shrink-0">
          <p className="text-center text-[10px] text-text-muted/60 leading-none">
            Powered by FlintTrade AI
          </p>
        </div>
      </GlassCard>
    </motion.div>
  );
}

// ---------------------------------------------------------------------------
// Main — AITutorPill
// ---------------------------------------------------------------------------

export function AITutorPill() {
  const [isOpen, setIsOpen] = useState(false);
  const location = useLocation();

  const aiTutorEnabled = useSkillStore((state) => state.helpPrefs.aiTutor);
  const setCurrentRoute = useAIConversationStore((state) => state.setCurrentRoute);
  const isConfigured = useSettingsStore((s) => s.llm.provider.length > 0);
  const activeWidget = useActiveWidgetContext();

  // Keep route in the conversation store in sync
  useEffect(() => {
    setCurrentRoute(location.pathname);
  }, [location.pathname, setCurrentRoute]);

  // Sync LLM config from backend once on mount
  useEffect(() => {
    void fetchAdvisorStatus();
  }, []);

  const handleClose = useCallback(() => setIsOpen(false), []);
  const handleOpen = useCallback(() => setIsOpen(true), []);

  // Only render when the preference is enabled
  if (!aiTutorEnabled) return null;

  const routeName = routeLabel(location.pathname);
  const reduced = motionConfig.prefersReducedMotion();

  return (
    /*
     * Fixed bottom-right, z-50.
     * bottom-16 leaves room above the TickerBar (h-8/h-10).
     * Hidden on xs screens (< sm) via `hidden sm:flex`.
     */
    <div
      className="fixed bottom-16 right-4 z-50 hidden sm:flex flex-col items-end gap-2"
      aria-live="polite"
    >
      <AnimatePresence mode="wait">
        {isOpen ? (
          <motion.div
            key="panel"
            initial={reduced ? { opacity: 0 } : { opacity: 0, y: 12, scale: 0.95 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={reduced ? { opacity: 0 } : { opacity: 0, y: 8, scale: 0.95 }}
            transition={{ duration: DURATION.normal, ease: isOpen ? EASE_ENTER : EASE_EXIT }}
          >
            <ExpandedPanel
              onClose={handleClose}
              routeName={routeName}
              currentRoute={location.pathname}
              isConfigured={isConfigured}
              activeWidget={activeWidget}
            />
          </motion.div>
        ) : (
          <motion.div
            key="pill"
            initial={reduced ? { opacity: 0 } : { opacity: 0, scale: 0.9 }}
            animate={{ opacity: 1, scale: 1 }}
            exit={reduced ? { opacity: 0 } : { opacity: 0, scale: 0.9 }}
            transition={{ duration: DURATION.fast, ease: EASE_ENTER }}
          >
            <Pill onClick={handleOpen} />
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

export default AITutorPill;
