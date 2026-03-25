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
import { useAIConversationStore } from "../aiConversationStore";
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
  });
  localStorage.clear();
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
    expect(parsed.version).toBe(1);
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
