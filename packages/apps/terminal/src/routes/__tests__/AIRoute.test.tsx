/**
 * AIRoute.test.tsx
 *
 * Smoke tests for the /ai AI Center page.
 * Mocks stores, hooks, framer-motion, and API services.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import "@testing-library/jest-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";

const aiSessionMocks = vi.hoisted(() => ({
  importAiSession: vi.fn(),
  getAiSession: vi.fn(),
}));

vi.mock("@/services/ftApi.ai", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/services/ftApi.ai")>();
  return {
    ...actual,
    importAiSession: aiSessionMocks.importAiSession,
    // The store routes saves/imports through the chunked helper; alias it to
    // the same mock so the call-shape assertions cover both entry points.
    importAiSessionChunked: aiSessionMocks.importAiSession,
    getAiSession: aiSessionMocks.getAiSession,
  };
});

const signalStreamMocks = vi.hoisted(() => {
  const state: {
    connected: boolean;
    replayLoss: null | {
      reason: string;
      requested_event_id: number;
      oldest_available_event_id: number | null;
      newest_available_event_id: number;
    };
    clearReplayLoss: ReturnType<typeof vi.fn>;
  } = {
    connected: false,
    replayLoss: null,
    clearReplayLoss: vi.fn(),
  };
  return { state, hook: vi.fn(() => state) };
});

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

vi.mock("framer-motion", () => ({
  motion: {
    div: ({ children, ...props }: Record<string, unknown>) => {
      const { initial: _i, animate: _a, exit: _e, variants: _v, transition: _t, layoutId: _l, ...rest } = props;
      return <div {...rest}>{children as React.ReactNode}</div>;
    },
    span: ({ children, ...props }: Record<string, unknown>) => {
      const { initial: _i, animate: _a, exit: _e, transition: _t, ...rest } = props;
      return <span {...rest}>{children as React.ReactNode}</span>;
    },
  },
  AnimatePresence: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

vi.mock("@/lib/motion", () => ({
  motionConfig: {
    prefersReducedMotion: () => true,
    duration: { fast: 0.1, normal: 0.2, slow: 0.3 },
    ease: { enter: [0, 0, 1, 1], exit: [0, 0, 1, 1] },
    transitions: { fade: { duration: 0.2 } },
    stagger: () => ({ duration: 0 }),
  },
  EASE_ENTER: [0.22, 1, 0.36, 1],
  EASE_EXIT: [0.0, 0.0, 0.58, 1.0],
  EASE_MOVE: [0.0, 0.0, 0.58, 1.0],
  DURATION: { fast: 0.15, normal: 0.3, slow: 0.5 },
}));

vi.mock("@/components/help/SpotlightTour", () => ({
  SpotlightTour: () => null,
}));

vi.mock("@/components/ui/scroll-area", () => ({
  ScrollArea: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}));

vi.mock("@/lib/tourDefinitions", () => ({
  TOUR_DEFINITIONS: {},
}));

vi.mock("@/hooks/useSkillLevel", () => ({
  useSkillLevel: vi.fn().mockReturnValue("intermediate"),
}));

vi.mock("@/hooks/useSignals", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/hooks/useSignals")>();
  return { ...actual, useSignalStream: signalStreamMocks.hook };
});

vi.mock("@/stores/skillStore", () => ({
  useSkillStore: Object.assign(
    vi.fn((selector: (state: Record<string, unknown>) => unknown) =>
      selector({ globalLevel: "intermediate" }),
    ),
    {
      getState: () => ({ globalLevel: "intermediate", trackAction: vi.fn() }),
      setState: vi.fn(),
    },
  ),
}));

vi.mock("@/widgets/utility/AIAdvisor/AIAdvisorWidget", () => ({
  default: () => <div data-testid="ai-advisor-widget">AI Advisor</div>,
}));

vi.mock("@/routes/ai/AISuggestionsPanel", () => ({
  default: () => <div data-testid="ai-suggestions-panel" />,
}));

vi.mock("@/services/ftApi", () => ({
  analyzeSentiment: vi.fn(),
  queryKnowledge: vi.fn(),
  getRecentSignals: vi.fn().mockResolvedValue({
    signals: [
      {
        event_id: 9,
        timestamp: "2026-07-10T09:20:00+05:30",
        symbol: "NIFTY",
        exchange: "NSE_INDEX",
        signal_type: "BUY",
        source: "ml",
        method: "ml_model",
        indicator: "LightGBM",
        value: 24500,
        threshold: 0,
        confidence: 0.81,
        message: "NIFTY scheduled ml model signal: BUY",
        metadata: { turbulence_score: 0.2 },
      },
    ],
  }),
}));

// ---------------------------------------------------------------------------
// Import after mocks
// ---------------------------------------------------------------------------

import AIRoute, { signalEventToCard } from "../AIRoute";
import { getRecentSignals, queryKnowledge } from "@/services/ftApi";
import type { SignalEvent } from "@/services/ftApi";
import { useSkillLevel } from "@/hooks/useSkillLevel";
import { useModeStore } from "@/stores/modeStore";
import { useAuthStore } from "@/stores/authStore";
import { useAIConversationStore } from "@/stores/aiConversationStore";
import type { Message } from "@/stores/aiConversationStore";

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

function renderAI(initialEntry = "/ai") {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <QueryClientProvider client={qc}>
        <AIRoute />
      </QueryClientProvider>
    </MemoryRouter>,
  );
}

function storeMessage(overrides: Partial<Message> = {}): Message {
  return {
    id: "m1",
    role: "user",
    content: "What is theta?",
    timestamp: 1_700_000_000_000,
    ...overrides,
  };
}

describe("AIRoute", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
    signalStreamMocks.state.connected = false;
    signalStreamMocks.state.replayLoss = null;
    useModeStore.setState({ mode: "explore" });
    useAuthStore.setState({ token: null });
    useAIConversationStore.setState({
      messages: [],
      isStreaming: false,
      currentRoute: "/",
      conversationId: null,
    });
  });

  it("renders the AI Center heading", () => {
    renderAI();

    expect(screen.getByText("AI Center")).toBeInTheDocument();
  });

  it("owns the signal stream at route scope before the Signals overlay opens", () => {
    renderAI();

    expect(screen.queryByText("Trading Signals")).not.toBeInTheDocument();
    expect(signalStreamMocks.hook).toHaveBeenCalled();
  });

  it("keeps the stream-qualified event identity in the signal card model", () => {
    const event: SignalEvent = {
      stream_id: "replacement-boot",
      event_id: 1,
      timestamp: "2026-07-11T10:00:00+05:30",
      symbol: "NIFTY",
      exchange: "NSE_INDEX",
      signal_type: "BUY",
      source: "rule",
      method: "RSI",
      indicator: "RSI",
      value: 28,
      threshold: 30,
      confidence: 0.8,
      message: "Signal after restart",
      metadata: {},
    };

    expect(signalEventToCard(event)).toMatchObject({
      stream_id: "replacement-boot",
      event_id: 1,
    });
  });

  it("shows navigation with Chat and Signals buttons", () => {
    renderAI();

    const nav = screen.getByRole("navigation", { name: /ai section navigation/i });
    expect(nav).toBeInTheDocument();
    expect(screen.getByLabelText("Chat")).toBeInTheDocument();
    expect(screen.getByLabelText("Signals")).toBeInTheDocument();
  });

  it("keeps AI section navigation in normal flow so it cannot cover the chat composer", () => {
    renderAI();

    const nav = screen.getByRole("navigation", { name: /ai section navigation/i });
    expect(nav).not.toHaveClass("absolute");
    expect(nav).not.toHaveClass("bottom-5");
  });

  it("shows rule, ML, and fallback signal sources truthfully in Explore mode", async () => {
    vi.mocked(getRecentSignals).mockRejectedValue(new Error("backend unavailable"));
    const user = userEvent.setup();
    renderAI();

    await user.click(screen.getByLabelText("Signals"));

    expect(await screen.findByText("Trading Signals")).toBeInTheDocument();
    expect(screen.getByText("Rule")).toBeInTheDocument();
    expect(screen.getByText("ML")).toBeInTheDocument();
    expect(screen.getByText("Fallback")).toBeInTheDocument();
    expect(screen.getAllByText("NSE_INDEX")).toHaveLength(3);
    expect(screen.getByText("Polling")).toBeInTheDocument();
    expect(signalStreamMocks.hook).toHaveBeenCalled();
    expect(screen.queryByText("ML-Powered Signals")).not.toBeInTheDocument();
    expect(screen.queryByText("Signal service unavailable.")).not.toBeInTheDocument();
    expect(getRecentSignals).not.toHaveBeenCalled();
  });

  it("surfaces live stream and replay-loss state in the production Signals view", async () => {
    signalStreamMocks.state.connected = true;
    signalStreamMocks.state.replayLoss = {
      reason: "cursor_before_retained",
      requested_event_id: 12,
      oldest_available_event_id: 40,
      newest_available_event_id: 139,
    };
    const user = userEvent.setup();
    renderAI();

    await user.click(screen.getByLabelText("Signals"));

    expect(await screen.findByText("Live")).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent(
      "Signal history gap detected. Recent signals refreshed.",
    );
    await user.click(screen.getByRole("button", { name: "Dismiss signal history notice" }));
    expect(signalStreamMocks.state.clearReplayLoss).toHaveBeenCalledOnce();
  });

  it("renders the generated knowledge answer even when no source chunks are returned", async () => {
    vi.mocked(useSkillLevel).mockReturnValue("advanced");
    vi.mocked(queryKnowledge).mockResolvedValue({
      answer: "I can only help with trading and market-related questions.",
      results: [],
    });
    const user = userEvent.setup();
    renderAI();

    await user.click(screen.getByLabelText("KB"));
    await user.type(screen.getByLabelText("Knowledge base query"), "Tell me a bedtime story");
    await user.click(screen.getByRole("button", { name: "Query" }));

    expect(
      await screen.findByText("I can only help with trading and market-related questions."),
    ).toBeInTheDocument();
    expect(screen.queryByText("Knowledge base not indexed. Index your docs in AI Settings."))
      .not.toBeInTheDocument();
  });

  it("renders a generated answer with its source chunks", async () => {
    vi.mocked(useSkillLevel).mockReturnValue("advanced");
    vi.mocked(queryKnowledge).mockResolvedValue({
      answer: "Theta measures option time decay.",
      results: [{ content: "Theta falls as expiry approaches.", source: "options.md", score: 0.91 }],
    });
    const user = userEvent.setup();
    renderAI();

    await user.click(screen.getByLabelText("KB"));
    await user.type(screen.getByLabelText("Knowledge base query"), "What is theta?");
    await user.click(screen.getByRole("button", { name: "Query" }));

    expect(await screen.findByText("Theta measures option time decay.")).toBeInTheDocument();
    expect(screen.getByText("options.md")).toBeInTheDocument();
    expect(screen.getByText("Theta falls as expiry approaches.")).toBeInTheDocument();
  });

  it("renders a neutral empty state when no indexed document matches", async () => {
    vi.mocked(useSkillLevel).mockReturnValue("advanced");
    vi.mocked(queryKnowledge).mockResolvedValue({ answer: "", results: [] });
    const user = userEvent.setup();
    renderAI();

    await user.click(screen.getByLabelText("KB"));
    await user.type(screen.getByLabelText("Knowledge base query"), "Unknown adjustment");
    await user.click(screen.getByRole("button", { name: "Query" }));

    expect(await screen.findByText("No matching documents.")).toBeInTheDocument();
    expect(screen.queryByText(/AI Settings/)).not.toBeInTheDocument();
  });

  it("renders actionable guidance when the RAG runtime is unavailable", async () => {
    vi.mocked(useSkillLevel).mockReturnValue("advanced");
    vi.mocked(queryKnowledge).mockRejectedValue(new Error("RAG engine not available"));
    const user = userEvent.setup();
    renderAI();

    await user.click(screen.getByLabelText("KB"));
    await user.type(screen.getByLabelText("Knowledge base query"), "What is theta?");
    await user.click(screen.getByRole("button", { name: "Query" }));

    expect(
      await screen.findByText("Knowledge service unavailable. Install the FlintTrade RAG dependencies and restart."),
    ).toBeInTheDocument();
  });

  it("distinguishes a disabled RAG runtime from missing dependencies", async () => {
    vi.mocked(useSkillLevel).mockReturnValue("advanced");
    vi.mocked(queryKnowledge).mockRejectedValue(new Error("RAG runtime disabled"));
    const user = userEvent.setup();
    renderAI();

    await user.click(screen.getByLabelText("KB"));
    await user.type(screen.getByLabelText("Knowledge base query"), "What is theta?");
    await user.click(screen.getByRole("button", { name: "Query" }));

    expect(
      await screen.findByText("Knowledge service is disabled. Enable FLINTTRADE_RAG_ENABLED and restart."),
    ).toBeInTheDocument();
    expect(screen.queryByText(/Install the FlintTrade RAG dependencies/)).not.toBeInTheDocument();
  });

  it("accepts the older response envelope when answer is absent", async () => {
    vi.mocked(useSkillLevel).mockReturnValue("advanced");
    vi.mocked(queryKnowledge).mockResolvedValue({
      results: [{ content: "Legacy source content.", source: "legacy.md", score: 0.8 }],
    });
    const user = userEvent.setup();
    renderAI();

    await user.click(screen.getByLabelText("KB"));
    await user.type(screen.getByLabelText("Knowledge base query"), "Legacy query");
    await user.click(screen.getByRole("button", { name: "Query" }));

    expect(await screen.findByText("legacy.md")).toBeInTheDocument();
    expect(screen.getByText("Legacy source content.")).toBeInTheDocument();
  });

  // -------------------------------------------------------------------------
  // Saved conversations — backend session store + one-time legacy import
  // -------------------------------------------------------------------------

  it("runs the one-time saved-chat import on mount and removes each key after success", async () => {
    useModeStore.setState({ mode: "live" });
    useAuthStore.setState({ token: "real-jwt" });
    localStorage.setItem(
      "flinttrade:saved-chat:legacy1",
      JSON.stringify({ messages: [storeMessage({ content: "Old saved chat" })], savedAt: 1 }),
    );
    aiSessionMocks.importAiSession.mockResolvedValue({ session_id: "legacy1" });

    renderAI();

    await waitFor(() =>
      expect(aiSessionMocks.importAiSession).toHaveBeenCalledWith({
        id: "legacy1",
        surface: "saved-chat",
        messages: [{ role: "user", content: "Old saved chat", timestamp: 1_700_000_000_000 }],
      }),
    );
    await waitFor(() =>
      expect(localStorage.getItem("flinttrade:saved-chat:legacy1")).toBeNull(),
    );
  });

  it("skips the legacy saved-chat import in Explore mode", async () => {
    useAuthStore.setState({ token: "real-jwt" });
    localStorage.setItem(
      "flinttrade:saved-chat:legacy1",
      JSON.stringify({ messages: [storeMessage()], savedAt: 1 }),
    );

    renderAI();

    await waitFor(() => expect(screen.getByText("AI Center")).toBeInTheDocument());
    expect(aiSessionMocks.importAiSession).not.toHaveBeenCalled();
    expect(localStorage.getItem("flinttrade:saved-chat:legacy1")).not.toBeNull();
  });

  it("restores a ?chat= conversation from the backend session store first", async () => {
    aiSessionMocks.getAiSession.mockResolvedValue({
      id: "abc",
      surface: "saved-chat",
      title: "Saved chat",
      started_at: "2026-07-19T10:00:00+05:30",
      last_at: "2026-07-19T10:05:00+05:30",
      messages: [
        { id: "b1", role: "user", content: "What is theta?", created_at: "2026-07-19T10:00:00.000Z" },
      ],
    });

    renderAI("/ai?chat=abc");

    await waitFor(() =>
      expect(useAIConversationStore.getState().messages).toHaveLength(1),
    );
    expect(useAIConversationStore.getState().messages[0]).toMatchObject({
      role: "user",
      content: "What is theta?",
      timestamp: Date.parse("2026-07-19T10:00:00.000Z"),
    });
    expect(useAIConversationStore.getState().conversationId).toBe("abc");
  });

  it("falls back to the legacy localStorage snapshot for old ?chat= links", async () => {
    aiSessionMocks.getAiSession.mockRejectedValue(new Error("HTTP 404"));
    localStorage.setItem(
      "flinttrade:saved-chat:old1",
      JSON.stringify({ messages: [storeMessage({ content: "Legacy share" })], savedAt: 1 }),
    );

    renderAI("/ai?chat=old1");

    await waitFor(() =>
      expect(useAIConversationStore.getState().messages).toHaveLength(1),
    );
    expect(useAIConversationStore.getState().messages[0].content).toBe("Legacy share");
  });

  it("shares by saving to the backend session store and confirms with Copied", async () => {
    useAIConversationStore.setState({
      messages: [storeMessage()],
      conversationId: "conv-1",
    });
    aiSessionMocks.importAiSession.mockResolvedValue({ session_id: "conv-1" });
    const user = userEvent.setup();
    renderAI();

    await user.click(screen.getByRole("button", { name: "Share conversation" }));

    expect(await screen.findByText("Copied")).toBeInTheDocument();
    expect(aiSessionMocks.importAiSession).toHaveBeenCalledWith(
      expect.objectContaining({ id: "conv-1", surface: "saved-chat" }),
    );
    // No legacy localStorage snapshot is written any more.
    expect(localStorage.getItem("flinttrade:saved-chat:conv-1")).toBeNull();
  });

  it("reports an honest failure when the share save is refused", async () => {
    useAIConversationStore.setState({
      messages: [storeMessage()],
      conversationId: "conv-1",
    });
    aiSessionMocks.importAiSession.mockRejectedValue(new Error("session store unavailable"));
    const user = userEvent.setup();
    renderAI();

    await user.click(screen.getByRole("button", { name: "Share conversation" }));

    expect(await screen.findByText("Share failed")).toBeInTheDocument();
    expect(screen.queryByText("Copied")).not.toBeInTheDocument();
  });
});
