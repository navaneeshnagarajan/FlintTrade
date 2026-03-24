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

  // Actions
  addMessage: (role: "user" | "assistant", content: string, route?: string) => void;
  setStreaming: (streaming: boolean) => void;
  setCurrentRoute: (route: string) => void;
  clearMessages: () => void;
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

const storeImpl: StateCreator<
  AIConversationState,
  [["zustand/persist", unknown]]
> = (set) => ({
  messages: [],
  isStreaming: false,
  currentRoute: "/",

  addMessage: (role, content, route) =>
    set((state) => ({
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

  clearMessages: () => set({ messages: [], isStreaming: false }),
});

// ---------------------------------------------------------------------------
// Persist config — messages + route, not the streaming flag (transient)
// ---------------------------------------------------------------------------

const persistedStore = persist(storeImpl, {
  name: "flinttrade:ai-conversation",
  version: 1,
  partialize: (state) => ({
    messages: state.messages,
    currentRoute: state.currentRoute,
  }),
});

// ---------------------------------------------------------------------------
// Export — devtools in dev only, matches skillStore pattern
// ---------------------------------------------------------------------------

export const useAIConversationStore = import.meta.env.DEV
  ? create<AIConversationState>()(devtools(persistedStore, { name: "ai-conversation" }))
  : create<AIConversationState>()(persistedStore);
