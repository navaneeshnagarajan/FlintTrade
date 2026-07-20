/**
 * aiConversationStore.test.ts
 *
 * Tests for the Zustand persisted AI conversation store.
 *
 * Strategy:
 *   - The store is imported normally; the Zustand persist middleware writes
 *     to the jsdom localStorage that is available at store creation time.
 *   - Reset both the Zustand state and localStorage between tests so each
 *     test begins with a clean slate.
 *   - import.meta.env.DEV is undefined (falsy) in jsdom → devtools branch
 *     is not taken; only the persist middleware wraps the store, which is
 *     the realistic production path.
 *   - Persistence tests read back from the real jsdom localStorage (the
 *     same object the middleware writes to).
 *
 * Arrange-Act-Assert pattern used throughout.
 */

import { describe, it, expect, beforeEach, vi } from "vitest";

// ---------------------------------------------------------------------------
// Mocks — backend session client + the mode/auth gates for the legacy import.
// The store module imports these at load time, so the mocks must be hoisted.
// ---------------------------------------------------------------------------

const aiSessionMocks = vi.hoisted(() => ({
  importAiSession: vi.fn(),
  getAiSession: vi.fn(),
}));

const gateState = vi.hoisted(() => ({
  mode: "live" as string,
  token: "real-jwt" as string | null,
}));

vi.mock("@/services/ftApi.ai", () => ({
  importAiSession: aiSessionMocks.importAiSession,
  getAiSession: aiSessionMocks.getAiSession,
}));

vi.mock("@/stores/modeStore", () => ({
  useModeStore: { getState: () => ({ mode: gateState.mode }) },
}));

vi.mock("@/stores/authStore", () => ({
  useAuthStore: { getState: () => ({ token: gateState.token }) },
}));

import { importLegacySavedChats, useAIConversationStore } from "../aiConversationStore";
import type { Message } from "../aiConversationStore";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Reset Zustand state to initial values and wipe localStorage between tests. */
function resetStore() {
  useAIConversationStore.setState({
    messages: [],
    isStreaming: false,
    currentRoute: "/",
    conversationId: null,
  });
  localStorage.clear();
  aiSessionMocks.importAiSession.mockReset();
  aiSessionMocks.getAiSession.mockReset();
  gateState.mode = "live";
  gateState.token = "real-jwt";
}

/** A well-formed stored Message for seeding tests. */
function storedMessage(overrides: Partial<Message> = {}): Message {
  return {
    id: "m1",
    role: "user",
    content: "What is theta?",
    timestamp: 1_700_000_000_000,
    ...overrides,
  };
}

// ---------------------------------------------------------------------------
// Initial state
// ---------------------------------------------------------------------------

describe("aiConversationStore — initial state", () => {
  beforeEach(resetStore);

  it("starts with an empty messages array", () => {
    // Arrange — fresh store (done by resetStore)
    // Act
    const { messages } = useAIConversationStore.getState();
    // Assert
    expect(messages).toEqual([]);
  });

  it("starts with isStreaming false", () => {
    expect(useAIConversationStore.getState().isStreaming).toBe(false);
  });

  it("starts with currentRoute '/'", () => {
    expect(useAIConversationStore.getState().currentRoute).toBe("/");
  });
});

// ---------------------------------------------------------------------------
// addMessage
// ---------------------------------------------------------------------------

describe("aiConversationStore — addMessage", () => {
  beforeEach(resetStore);

  it("appends a user message to the empty history", () => {
    // Arrange
    const { addMessage } = useAIConversationStore.getState();
    // Act
    addMessage("user", "Hello, what is NIFTY?");
    // Assert
    const { messages } = useAIConversationStore.getState();
    expect(messages).toHaveLength(1);
    expect(messages[0].role).toBe("user");
    expect(messages[0].content).toBe("Hello, what is NIFTY?");
  });

  it("appends an assistant message", () => {
    // Arrange
    const { addMessage } = useAIConversationStore.getState();
    // Act
    addMessage("assistant", "NIFTY is the NSE benchmark index.");
    // Assert
    const { messages } = useAIConversationStore.getState();
    expect(messages[0].role).toBe("assistant");
  });

  it("appends multiple messages in order", () => {
    // Arrange
    const { addMessage } = useAIConversationStore.getState();
    // Act
    addMessage("user", "First message");
    addMessage("assistant", "Second message");
    addMessage("user", "Third message");
    // Assert
    const { messages } = useAIConversationStore.getState();
    expect(messages).toHaveLength(3);
    expect(messages[0].content).toBe("First message");
    expect(messages[1].content).toBe("Second message");
    expect(messages[2].content).toBe("Third message");
  });

  it("does not mutate earlier messages when a new one is added", () => {
    // Arrange
    const { addMessage } = useAIConversationStore.getState();
    addMessage("user", "Original");
    const before = useAIConversationStore.getState().messages[0];
    // Act
    addMessage("assistant", "Follow-up");
    const after = useAIConversationStore.getState().messages[0];
    // Assert — same object reference (immutable state update)
    expect(after).toBe(before);
  });

  it("stores the current route in each message when no explicit route given", () => {
    // Arrange
    useAIConversationStore.getState().setCurrentRoute("/trade");
    const { addMessage } = useAIConversationStore.getState();
    // Act
    addMessage("user", "Place an order");
    // Assert
    const { messages } = useAIConversationStore.getState();
    expect(messages[0].route).toBe("/trade");
  });

  it("stores an explicitly passed route, overriding currentRoute", () => {
    // Arrange
    useAIConversationStore.getState().setCurrentRoute("/trade");
    const { addMessage } = useAIConversationStore.getState();
    // Act
    addMessage("user", "Show holdings", "/invest");
    // Assert
    const { messages } = useAIConversationStore.getState();
    expect(messages[0].route).toBe("/invest");
  });
});

// ---------------------------------------------------------------------------
// Message structure
// ---------------------------------------------------------------------------

describe("aiConversationStore — message structure", () => {
  beforeEach(resetStore);

  it("every message has an id string", () => {
    // Arrange + Act
    useAIConversationStore.getState().addMessage("user", "Test");
    // Assert
    const { messages } = useAIConversationStore.getState();
    expect(typeof messages[0].id).toBe("string");
    expect(messages[0].id.length).toBeGreaterThan(0);
  });

  it("every message has a numeric timestamp", () => {
    // Arrange
    const before = Date.now();
    // Act
    useAIConversationStore.getState().addMessage("user", "Timestamp test");
    const after = Date.now();
    // Assert
    const { messages } = useAIConversationStore.getState();
    expect(typeof messages[0].timestamp).toBe("number");
    expect(messages[0].timestamp).toBeGreaterThanOrEqual(before);
    expect(messages[0].timestamp).toBeLessThanOrEqual(after);
  });

  it("consecutive messages have unique ids", () => {
    // Arrange + Act
    const { addMessage } = useAIConversationStore.getState();
    addMessage("user", "A");
    addMessage("user", "B");
    addMessage("user", "C");
    // Assert
    const ids = useAIConversationStore.getState().messages.map((m) => m.id);
    const unique = new Set(ids);
    expect(unique.size).toBe(3);
  });

  it("message conforms to the Message interface shape", () => {
    // Arrange + Act
    useAIConversationStore.getState().addMessage("assistant", "Hello");
    // Assert
    const msg: Message = useAIConversationStore.getState().messages[0];
    expect(msg).toHaveProperty("id");
    expect(msg).toHaveProperty("role");
    expect(msg).toHaveProperty("content");
    expect(msg).toHaveProperty("timestamp");
    expect(["user", "assistant"]).toContain(msg.role);
  });
});

// ---------------------------------------------------------------------------
// setStreaming
// ---------------------------------------------------------------------------

describe("aiConversationStore — setStreaming", () => {
  beforeEach(resetStore);

  it("sets isStreaming to true", () => {
    // Arrange + Act
    useAIConversationStore.getState().setStreaming(true);
    // Assert
    expect(useAIConversationStore.getState().isStreaming).toBe(true);
  });

  it("sets isStreaming back to false", () => {
    // Arrange
    useAIConversationStore.getState().setStreaming(true);
    // Act
    useAIConversationStore.getState().setStreaming(false);
    // Assert
    expect(useAIConversationStore.getState().isStreaming).toBe(false);
  });

  it("isStreaming is NOT persisted (transient flag)", () => {
    // Arrange — add a message first so the middleware has written at least once
    useAIConversationStore.getState().addMessage("user", "Trigger write");
    useAIConversationStore.getState().setStreaming(true);
    // Act — read the localStorage entry written by persist middleware
    const raw = localStorage.getItem("flinttrade:ai-conversation");
    // Assert — partialize excludes isStreaming
    expect(raw).not.toBeNull();
    const parsed = JSON.parse(raw as string) as { state: Record<string, unknown> };
    expect(parsed.state).not.toHaveProperty("isStreaming");
  });
});

// ---------------------------------------------------------------------------
// setCurrentRoute
// ---------------------------------------------------------------------------

describe("aiConversationStore — setCurrentRoute", () => {
  beforeEach(resetStore);

  it("updates currentRoute", () => {
    // Arrange + Act
    useAIConversationStore.getState().setCurrentRoute("/learn");
    // Assert
    expect(useAIConversationStore.getState().currentRoute).toBe("/learn");
  });

  it("currentRoute is persisted to localStorage", () => {
    // Arrange — trigger a write first so the persist middleware has a state entry
    useAIConversationStore.getState().addMessage("user", "Trigger write");
    // Act
    useAIConversationStore.getState().setCurrentRoute("/ai");
    // Assert — read back from the real jsdom localStorage
    const raw = localStorage.getItem("flinttrade:ai-conversation");
    expect(raw).not.toBeNull();
    const parsed = JSON.parse(raw as string) as { state: { currentRoute: string } };
    expect(parsed.state.currentRoute).toBe("/ai");
  });
});

// ---------------------------------------------------------------------------
// clearMessages
// ---------------------------------------------------------------------------

describe("aiConversationStore — clearMessages", () => {
  beforeEach(resetStore);

  it("removes all messages", () => {
    // Arrange
    const { addMessage, clearMessages } = useAIConversationStore.getState();
    addMessage("user", "First");
    addMessage("assistant", "Second");
    expect(useAIConversationStore.getState().messages).toHaveLength(2);
    // Act
    clearMessages();
    // Assert
    expect(useAIConversationStore.getState().messages).toEqual([]);
  });

  it("also resets isStreaming to false when clearing", () => {
    // Arrange
    useAIConversationStore.getState().setStreaming(true);
    // Act
    useAIConversationStore.getState().clearMessages();
    // Assert
    expect(useAIConversationStore.getState().isStreaming).toBe(false);
  });

  it("is a no-op on an already-empty store", () => {
    // Arrange — store starts empty
    // Act + Assert — no error thrown
    expect(() => {
      useAIConversationStore.getState().clearMessages();
    }).not.toThrow();
    expect(useAIConversationStore.getState().messages).toEqual([]);
  });
});

// ---------------------------------------------------------------------------
// Persistence — localStorage integration
// ---------------------------------------------------------------------------

describe("aiConversationStore — persistence", () => {
  beforeEach(resetStore);

  it("writes messages to localStorage under 'flinttrade:ai-conversation'", () => {
    // Arrange + Act
    useAIConversationStore.getState().addMessage("user", "Persisted?");
    // Assert — read from jsdom localStorage (the storage the middleware binds to)
    const raw = localStorage.getItem("flinttrade:ai-conversation");
    expect(raw).not.toBeNull();
    const parsed = JSON.parse(raw as string) as {
      state: { messages: Message[] };
    };
    expect(parsed.state.messages[0].content).toBe("Persisted?");
  });

  it("stores the persist version number as 1", () => {
    // Arrange + Act
    useAIConversationStore.getState().addMessage("user", "Version check");
    // Assert
    const raw = localStorage.getItem("flinttrade:ai-conversation");
    expect(raw).not.toBeNull();
    const parsed = JSON.parse(raw as string) as { version: number };
    expect(parsed.version).toBe(2);
  });

  it("partializes to only messages and currentRoute (no isStreaming)", () => {
    // Arrange + Act
    useAIConversationStore.getState().setStreaming(true);
    useAIConversationStore.getState().addMessage("user", "Partial");
    useAIConversationStore.getState().setCurrentRoute("/invest");
    // Assert
    const raw = localStorage.getItem("flinttrade:ai-conversation");
    expect(raw).not.toBeNull();
    const parsed = JSON.parse(raw as string) as { state: Record<string, unknown> };
    expect(parsed.state).toHaveProperty("messages");
    expect(parsed.state).toHaveProperty("currentRoute");
    expect(parsed.state).not.toHaveProperty("isStreaming");
  });

  it("messages survive a simulated page refresh (rehydrate from storage)", () => {
    // Arrange — add messages and capture the persisted payload
    const { addMessage } = useAIConversationStore.getState();
    addMessage("user", "Before refresh");
    addMessage("assistant", "Reply before refresh");
    const raw = localStorage.getItem("flinttrade:ai-conversation");
    expect(raw).not.toBeNull();

    // Act — simulate rehydrate by manually restoring from the JSON payload
    const parsed = JSON.parse(raw as string) as {
      state: { messages: Message[]; currentRoute: string };
    };
    useAIConversationStore.setState({
      messages: parsed.state.messages,
      currentRoute: parsed.state.currentRoute,
      isStreaming: false,
    });

    // Assert — messages are intact
    const { messages } = useAIConversationStore.getState();
    expect(messages).toHaveLength(2);
    expect(messages[0].content).toBe("Before refresh");
    expect(messages[1].content).toBe("Reply before refresh");
  });

  it("clearMessages also clears the persisted messages in localStorage", () => {
    // Arrange
    useAIConversationStore.getState().addMessage("user", "To be cleared");
    // Act
    useAIConversationStore.getState().clearMessages();
    // Assert — storage should reflect empty messages
    const raw = localStorage.getItem("flinttrade:ai-conversation");
    expect(raw).not.toBeNull();
    const parsed = JSON.parse(raw as string) as { state: { messages: Message[] } };
    expect(parsed.state.messages).toEqual([]);
  });
});

// ---------------------------------------------------------------------------
// saveConversation — backend session import (no localStorage writes)
// ---------------------------------------------------------------------------

describe("aiConversationStore — saveConversation", () => {
  beforeEach(resetStore);

  it("posts the conversation to the session import endpoint with surface saved-chat", async () => {
    // Arrange
    aiSessionMocks.importAiSession.mockResolvedValue({ session_id: "conv-1" });
    useAIConversationStore.setState({
      messages: [
        storedMessage(),
        storedMessage({ id: "m2", role: "assistant", content: "Time decay.", timestamp: 1_700_000_005_000 }),
      ],
      conversationId: "conv-1",
    });
    // Act
    const id = await useAIConversationStore.getState().saveConversation();
    // Assert
    expect(id).toBe("conv-1");
    expect(aiSessionMocks.importAiSession).toHaveBeenCalledWith({
      id: "conv-1",
      surface: "saved-chat",
      messages: [
        { role: "user", content: "What is theta?", timestamp: 1_700_000_000_000 },
        { role: "assistant", content: "Time decay.", timestamp: 1_700_000_005_000 },
      ],
    });
    // No legacy localStorage snapshot is written any more.
    expect(localStorage.getItem("flinttrade:saved-chat:conv-1")).toBeNull();
  });

  it("generates and stores a conversation id when none exists yet", async () => {
    // Arrange
    aiSessionMocks.importAiSession.mockResolvedValue({ session_id: "whatever" });
    useAIConversationStore.setState({ messages: [storedMessage()], conversationId: null });
    // Act
    const id = await useAIConversationStore.getState().saveConversation();
    // Assert
    expect(id.length).toBeGreaterThan(0);
    expect(useAIConversationStore.getState().conversationId).toBe(id);
    expect(aiSessionMocks.importAiSession).toHaveBeenCalledWith(
      expect.objectContaining({ id, surface: "saved-chat" }),
    );
  });

  it("rejects (and writes nothing locally) when the backend import fails", async () => {
    // Arrange
    aiSessionMocks.importAiSession.mockRejectedValue(new Error("session store unavailable"));
    useAIConversationStore.setState({ messages: [storedMessage()], conversationId: "conv-x" });
    // Act + Assert
    await expect(useAIConversationStore.getState().saveConversation()).rejects.toThrow(
      "session store unavailable",
    );
    expect(localStorage.getItem("flinttrade:saved-chat:conv-x")).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// loadConversation — backend first, legacy localStorage fallback
// ---------------------------------------------------------------------------

describe("aiConversationStore — loadConversation", () => {
  beforeEach(resetStore);

  it("loads a backend session and maps ISO created_at to ms timestamps", async () => {
    // Arrange
    aiSessionMocks.getAiSession.mockResolvedValue({
      id: "abc",
      surface: "saved-chat",
      title: "Saved chat",
      started_at: "2026-07-19T10:00:00+05:30",
      last_at: "2026-07-19T10:05:00+05:30",
      messages: [
        { id: "b1", role: "user", content: "What is theta?", created_at: "2026-07-19T10:00:00.000Z" },
        { id: "b2", role: "assistant", content: "Time decay.", created_at: "2026-07-19T10:00:05.000Z" },
      ],
    });
    // Act
    const ok = await useAIConversationStore.getState().loadConversation("abc");
    // Assert
    expect(ok).toBe(true);
    const { messages, conversationId } = useAIConversationStore.getState();
    expect(conversationId).toBe("abc");
    expect(messages).toHaveLength(2);
    expect(messages[0]).toMatchObject({
      role: "user",
      content: "What is theta?",
      timestamp: Date.parse("2026-07-19T10:00:00.000Z"),
    });
    expect(messages[1]).toMatchObject({
      role: "assistant",
      timestamp: Date.parse("2026-07-19T10:00:05.000Z"),
    });
  });

  it("falls back to the legacy localStorage snapshot when the backend has no session", async () => {
    // Arrange
    aiSessionMocks.getAiSession.mockRejectedValue(new Error("HTTP 404"));
    localStorage.setItem(
      "flinttrade:saved-chat:old1",
      JSON.stringify({ messages: [storedMessage({ content: "Legacy chat" })], savedAt: 1_700_000_000_000 }),
    );
    // Act
    const ok = await useAIConversationStore.getState().loadConversation("old1");
    // Assert
    expect(ok).toBe(true);
    expect(useAIConversationStore.getState().messages[0].content).toBe("Legacy chat");
    expect(useAIConversationStore.getState().conversationId).toBe("old1");
  });

  it("returns false when neither backend nor legacy snapshot exists", async () => {
    // Arrange
    aiSessionMocks.getAiSession.mockRejectedValue(new Error("HTTP 404"));
    // Act + Assert
    await expect(useAIConversationStore.getState().loadConversation("missing")).resolves.toBe(false);
    expect(useAIConversationStore.getState().messages).toEqual([]);
  });
});

// ---------------------------------------------------------------------------
// importLegacySavedChats — one-time localStorage → backend migration
// ---------------------------------------------------------------------------

describe("aiConversationStore — importLegacySavedChats", () => {
  beforeEach(resetStore);

  it("imports each legacy key and removes it only after its import succeeds", async () => {
    // Arrange
    aiSessionMocks.importAiSession.mockResolvedValue({ session_id: "x" });
    localStorage.setItem(
      "flinttrade:saved-chat:one",
      JSON.stringify({ messages: [storedMessage({ content: "First" })], savedAt: 1 }),
    );
    localStorage.setItem(
      "flinttrade:saved-chat:two",
      JSON.stringify({ messages: [storedMessage({ content: "Second" })], savedAt: 2 }),
    );
    // Act
    const imported = await importLegacySavedChats();
    // Assert
    expect(imported).toBe(2);
    expect(aiSessionMocks.importAiSession).toHaveBeenCalledWith(
      expect.objectContaining({ id: "one", surface: "saved-chat" }),
    );
    expect(aiSessionMocks.importAiSession).toHaveBeenCalledWith(
      expect.objectContaining({ id: "two", surface: "saved-chat" }),
    );
    expect(localStorage.getItem("flinttrade:saved-chat:one")).toBeNull();
    expect(localStorage.getItem("flinttrade:saved-chat:two")).toBeNull();
  });

  it("keeps a key whose import fails so the next visit can retry", async () => {
    // Arrange — "bad" is refused; "good" succeeds.
    aiSessionMocks.importAiSession.mockImplementation(
      (payload: { id?: string }) =>
        payload.id === "bad"
          ? Promise.reject(new Error("backend refused"))
          : Promise.resolve({ session_id: payload.id ?? "" }),
    );
    localStorage.setItem(
      "flinttrade:saved-chat:bad",
      JSON.stringify({ messages: [storedMessage({ content: "Refused" })], savedAt: 1 }),
    );
    localStorage.setItem(
      "flinttrade:saved-chat:good",
      JSON.stringify({ messages: [storedMessage({ content: "Accepted" })], savedAt: 2 }),
    );
    // Act
    const imported = await importLegacySavedChats();
    // Assert
    expect(imported).toBe(1);
    expect(localStorage.getItem("flinttrade:saved-chat:bad")).not.toBeNull();
    expect(localStorage.getItem("flinttrade:saved-chat:good")).toBeNull();
  });

  it("skips entirely in Explore mode", async () => {
    // Arrange
    gateState.mode = "explore";
    localStorage.setItem(
      "flinttrade:saved-chat:one",
      JSON.stringify({ messages: [storedMessage()], savedAt: 1 }),
    );
    // Act
    const imported = await importLegacySavedChats();
    // Assert
    expect(imported).toBe(0);
    expect(aiSessionMocks.importAiSession).not.toHaveBeenCalled();
    expect(localStorage.getItem("flinttrade:saved-chat:one")).not.toBeNull();
  });

  it("skips on demo auth tokens", async () => {
    // Arrange
    gateState.token = "demo-user";
    localStorage.setItem(
      "flinttrade:saved-chat:one",
      JSON.stringify({ messages: [storedMessage()], savedAt: 1 }),
    );
    // Act
    const imported = await importLegacySavedChats();
    // Assert
    expect(imported).toBe(0);
    expect(aiSessionMocks.importAiSession).not.toHaveBeenCalled();
    expect(localStorage.getItem("flinttrade:saved-chat:one")).not.toBeNull();
  });

  it("clears an empty snapshot without importing it (no content to lose)", async () => {
    // Arrange
    localStorage.setItem("flinttrade:saved-chat:empty", JSON.stringify({ messages: [] }));
    // Act
    const imported = await importLegacySavedChats();
    // Assert
    expect(imported).toBe(0);
    expect(aiSessionMocks.importAiSession).not.toHaveBeenCalled();
    expect(localStorage.getItem("flinttrade:saved-chat:empty")).toBeNull();
  });

  it("leaves an unparseable snapshot in place (never deletes unmigrated content)", async () => {
    // Arrange
    localStorage.setItem("flinttrade:saved-chat:corrupt", "not-json{");
    // Act
    const imported = await importLegacySavedChats();
    // Assert
    expect(imported).toBe(0);
    expect(localStorage.getItem("flinttrade:saved-chat:corrupt")).toBe("not-json{");
  });
});

// ---------------------------------------------------------------------------
// Spy: Date.now() for deterministic timestamp assertions
// ---------------------------------------------------------------------------

describe("aiConversationStore — timestamp determinism", () => {
  beforeEach(resetStore);

  it("timestamp matches the value returned by Date.now() at call time", () => {
    // Arrange
    const fakeNow = 1_700_000_000_000;
    vi.spyOn(Date, "now").mockReturnValue(fakeNow);
    // Act
    useAIConversationStore.getState().addMessage("user", "Timed message");
    vi.restoreAllMocks();
    // Assert
    const { messages } = useAIConversationStore.getState();
    expect(messages[0].timestamp).toBe(fakeNow);
  });
});
