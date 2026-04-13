/**
 * aiConversationStore.ts
 *
 * Shared AI conversation state used by both the /ai route (AIAdvisorWidget)
 * and the AITutorPill floating assistant.
 *
 * Data enters through addMessage() only — never duplicated across stores.
 * Persisted to localStorage so the conversation survives page refreshes.
 *
 * State boundaries:
 *   - Messages, streaming flag, and route context live here.
 *   - Jotai atoms own real-time ticks — not used here.
 *   - TanStack Query owns REST responses — not used here.
 */

import { create } from "zustand";
import { devtools, persist } from "zustand/middleware";
import type { StateCreator } from "zustand";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  timestamp: number;
  /** Which app route the message was sent from (e.g. "/trade", "/learn") */
  route?: string;
}

export interface AIConversationState {
  messages: Message[];
  isStreaming: boolean;
  currentRoute: string;
  /** Unique conversation ID for sharing. Generated on first message. */
  conversationId: string | null;

  // Actions
  addMessage: (role: "user" | "assistant", content: string, route?: string) => void;
  setStreaming: (streaming: boolean) => void;
  setCurrentRoute: (route: string) => void;
  clearMessages: () => void;
  /** Save the current conversation to localStorage keyed by its ID. */
  saveConversation: () => string;
  /** Load a conversation by ID from localStorage. Returns true on success. */
  loadConversation: (id: string) => boolean;
}

// ---------------------------------------------------------------------------
// ID generator — simple timestamp + random suffix (no crypto dep needed)
// ---------------------------------------------------------------------------

function generateId(): string {
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 7)}`;
}

// ---------------------------------------------------------------------------
// Store implementation
// ---------------------------------------------------------------------------

/** localStorage key prefix for saved conversations. */
const SAVED_CHAT_PREFIX = "flinttrade:saved-chat:";

const storeImpl: StateCreator<
  AIConversationState,
  [["zustand/persist", unknown]]
> = (set, get) => ({
  messages: [],
  isStreaming: false,
  currentRoute: "/",
  conversationId: null,

  addMessage: (role, content, route) =>
    set((state) => ({
      // Generate a conversation ID on the first message if one does not exist.
      conversationId: state.conversationId ?? crypto.randomUUID(),
      messages: [
        ...state.messages,
        {
          id: generateId(),
          role,
          content,
          timestamp: Date.now(),
          route: route ?? state.currentRoute,
        },
      ],
    })),

  setStreaming: (streaming) => set({ isStreaming: streaming }),

  setCurrentRoute: (route) => set({ currentRoute: route }),

  clearMessages: () => set({ messages: [], isStreaming: false, conversationId: null }),

  saveConversation: () => {
    const state = get();
    const id = state.conversationId ?? crypto.randomUUID();
    if (!state.conversationId) {
      set({ conversationId: id });
    }
    try {
      localStorage.setItem(
        `${SAVED_CHAT_PREFIX}${id}`,
        JSON.stringify({ messages: state.messages, savedAt: Date.now() }),
      );
    } catch {
      // Storage full or unavailable — ignore silently.
    }
    return id;
  },

  loadConversation: (id: string) => {
    try {
      const raw = localStorage.getItem(`${SAVED_CHAT_PREFIX}${id}`);
      if (!raw) return false;
      const parsed = JSON.parse(raw) as { messages: Message[] };
      if (!Array.isArray(parsed.messages)) return false;
      set({ messages: parsed.messages, conversationId: id, isStreaming: false });
      return true;
    } catch {
      return false;
    }
  },
});

// ---------------------------------------------------------------------------
// Persist config — messages + route, not the streaming flag (transient)
// ---------------------------------------------------------------------------

const persistedStore = persist(storeImpl, {
  name: "flinttrade:ai-conversation",
  version: 2,
  partialize: (state) => ({
    messages: state.messages,
    currentRoute: state.currentRoute,
    conversationId: state.conversationId,
  }),
});

// ---------------------------------------------------------------------------
// Export — devtools in dev only, matches skillStore pattern
// ---------------------------------------------------------------------------

export const useAIConversationStore = import.meta.env.DEV
  ? create<AIConversationState>()(devtools(persistedStore, { name: "ai-conversation" }))
  : create<AIConversationState>()(persistedStore);
