/**
 * aiConversationStore.ts
 *
 * Shared AI conversation state used by both the /ai route (AIAdvisorWidget)
 * and the AITutorPill floating assistant.
 *
 * Data enters through addMessage() only — never duplicated across stores.
 * The LIVE conversation is persisted to localStorage so it survives page
 * refreshes; SAVED conversations persist to the backend AI session store
 * (`/api/v1/ai/sessions/*`) with a legacy localStorage fallback for old
 * share links.
 *
 * State boundaries:
 *   - Messages, streaming flag, and route context live here.
 *   - Jotai atoms own real-time ticks — not used here.
 *   - TanStack Query owns REST responses — not used here.
 */

import { create } from "zustand";
import { devtools, persist } from "zustand/middleware";
import type { StateCreator } from "zustand";
import { z } from "zod";
import { safeParse } from "@/lib/safeParse";
import { getAiSession, importAiSession } from "@/services/ftApi.ai";
import type { AiSessionMessage } from "@/services/ftApi.ai";
import { useAuthStore } from "@/stores/authStore";
import { useModeStore } from "@/stores/modeStore";

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
  /**
   * Save the current conversation to the backend AI session store (surface
   * "saved-chat", id = conversation id). Resolves with the conversation id;
   * rejects when the backend refuses or is unreachable — nothing is written
   * locally, so a failed save is never silently claimed.
   */
  saveConversation: () => Promise<string>;
  /**
   * Load a conversation by ID — backend session store first, falling back to
   * the legacy localStorage snapshot for old share links. Resolves true on
   * success.
   */
  loadConversation: (id: string) => Promise<boolean>;
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

/** localStorage key prefix legacy saved conversations were stored under. */
const SAVED_CHAT_PREFIX = "flinttrade:saved-chat:";

// ---------------------------------------------------------------------------
// Zod schemas for persistence validation
// ---------------------------------------------------------------------------

const messageSchema = z.object({
  id: z.string(),
  role: z.enum(["user", "assistant"]),
  content: z.string(),
  timestamp: z.number(),
  route: z.string().optional(),
});

const savedChatSchema = z.object({
  messages: z.array(messageSchema),
});

/** Map a stored backend session message onto the store's Message shape (ISO `created_at` → ms). */
function toStoreMessage(message: AiSessionMessage): Message {
  const parsedMs = Date.parse(message.created_at);
  return {
    id: message.id,
    role: message.role === "user" ? "user" : "assistant",
    content: message.content,
    timestamp: Number.isFinite(parsedMs) ? parsedMs : Date.now(),
  };
}

/** True only for a real authenticated session — never demo/dev-bypass tokens. */
function hasRealAuthToken(): boolean {
  const token = useAuthStore.getState().token;
  return Boolean(token && token !== "demo-user" && token !== "dev-bypass");
}

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

  saveConversation: async () => {
    const state = get();
    const id = state.conversationId ?? crypto.randomUUID();
    if (!state.conversationId) {
      set({ conversationId: id });
    }
    await importAiSession({
      id,
      surface: "saved-chat",
      messages: state.messages.map((message) => ({
        role: message.role,
        content: message.content,
        timestamp: message.timestamp,
      })),
    });
    return id;
  },

  loadConversation: async (id: string) => {
    try {
      const session = await getAiSession(id);
      set({
        messages: session.messages.map(toStoreMessage),
        conversationId: id,
        isStreaming: false,
      });
      return true;
    } catch {
      // Backend unreachable, or the id predates server persistence — fall
      // through to the legacy localStorage snapshot for old share links.
    }
    const raw = localStorage.getItem(`${SAVED_CHAT_PREFIX}${id}`);
    if (!raw) return false;
    const parsed = safeParse(raw, savedChatSchema);
    if (!parsed) return false;
    set({ messages: parsed.messages, conversationId: id, isStreaming: false });
    return true;
  },
});

// ---------------------------------------------------------------------------
// One-time legacy saved-chat migration (localStorage → backend session store)
// ---------------------------------------------------------------------------

let legacyImportRun: Promise<number> | null = null;

async function runLegacySavedChatImport(): Promise<number> {
  // Skip in Explore mode and on demo auth — fabricated chats must never
  // persist server-side (same gate as the AIAdvisor session capture).
  if (useModeStore.getState().mode === "explore" || !hasRealAuthToken()) return 0;

  const keys: string[] = [];
  for (let i = 0; i < localStorage.length; i += 1) {
    const key = localStorage.key(i);
    if (key?.startsWith(SAVED_CHAT_PREFIX)) keys.push(key);
  }

  let imported = 0;
  for (const key of keys) {
    const raw = localStorage.getItem(key);
    if (raw === null) continue;
    const parsed = safeParse(raw, savedChatSchema);
    if (!parsed) continue; // Unparseable snapshot — keep it; never delete unmigrated content.
    if (parsed.messages.length === 0) {
      // An empty snapshot has no content to lose — clear it directly.
      localStorage.removeItem(key);
      continue;
    }
    const id = key.slice(SAVED_CHAT_PREFIX.length);
    try {
      await importAiSession({
        id,
        surface: "saved-chat",
        messages: parsed.messages.map((message) => ({
          role: message.role,
          content: message.content,
          timestamp: message.timestamp,
        })),
      });
    } catch {
      // Backend unreachable or refused — keep the key; the next visit retries
      // (content-hash dedupe on the backend makes re-imports safe).
      continue;
    }
    localStorage.removeItem(key);
    imported += 1;
  }
  return imported;
}

/**
 * One-time migration of legacy `flinttrade:saved-chat:*` localStorage
 * snapshots into the backend AI session store. Skipped in Explore mode and on
 * demo auth. Each key is removed ONLY after its import confirmed success;
 * failures leave the key in place for a retry on the next visit (backend
 * upsert/dedupe keeps that idempotent). Concurrent callers share one
 * in-flight run. Resolves with the number of conversations migrated.
 */
export function importLegacySavedChats(): Promise<number> {
  if (!legacyImportRun) {
    legacyImportRun = runLegacySavedChatImport().finally(() => {
      legacyImportRun = null;
    });
  }
  return legacyImportRun;
}

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
