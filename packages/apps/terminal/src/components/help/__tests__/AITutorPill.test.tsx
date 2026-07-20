/**
 * AITutorPill.test.tsx
 *
 * Tests for the floating AI tutor assistant — focused on the server-side
 * session capture: real (non-demo) auth sessions send `session_id` on
 * advisor requests (same gating as AIAdvisorWidget); demo sessions never do,
 * so fabricated chats cannot persist server-side.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import "@testing-library/jest-dom";
import { MemoryRouter } from "react-router-dom";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

const authState = vi.hoisted(() => ({
  token: null as string | null,
  status: "logged-out" as string,
}));

const settingsState = vi.hoisted(() => ({
  llm: { provider: "ollama", model: "llama3" },
  setLLM: vi.fn(),
}));

vi.mock("framer-motion", () => ({
  motion: {
    div: ({ children, ...props }: Record<string, unknown>) => {
      const { initial: _i, animate: _a, exit: _e, transition: _t, whileHover: _h, whileTap: _w, ...rest } = props;
      return <div {...rest}>{children as React.ReactNode}</div>;
    },
    span: ({ children, ...props }: Record<string, unknown>) => {
      const { initial: _i, animate: _a, exit: _e, transition: _t, ...rest } = props;
      return <span {...rest}>{children as React.ReactNode}</span>;
    },
    button: ({ children, ...props }: Record<string, unknown>) => {
      const { initial: _i, animate: _a, exit: _e, transition: _t, whileHover: _h, whileTap: _w, ...rest } = props;
      return <button {...rest}>{children as React.ReactNode}</button>;
    },
  },
  AnimatePresence: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

vi.mock("@/lib/motion", () => ({
  motionConfig: {
    prefersReducedMotion: () => true,
    stagger: () => ({ duration: 0 }),
  },
  EASE_ENTER: [0.22, 1, 0.36, 1],
  EASE_EXIT: [0.0, 0.0, 0.58, 1.0],
  DURATION: { fast: 0.15, normal: 0.3, slow: 0.5 },
}));

vi.mock("@/components/ui/scroll-area", () => ({
  ScrollArea: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}));

vi.mock("@/stores/skillStore", () => ({
  useSkillStore: vi.fn((selector: (state: { helpPrefs: { aiTutor: boolean } }) => unknown) =>
    selector({ helpPrefs: { aiTutor: true } }),
  ),
}));

vi.mock("@/stores/settingsStore", () => ({
  useSettingsStore: Object.assign(
    vi.fn((selector: (state: typeof settingsState) => unknown) => selector(settingsState)),
    { getState: () => settingsState },
  ),
}));

vi.mock("@/stores/authStore", () => ({
  useAuthStore: Object.assign(
    vi.fn((selector: (state: typeof authState) => unknown) => selector(authState)),
    { getState: () => authState },
  ),
}));

vi.mock("@/services/advisorApi", () => ({
  getAdvisorBase: () => "",
}));

import { AITutorPill } from "../AITutorPill";
import { useAIConversationStore } from "@/stores/aiConversationStore";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function renderPill() {
  return render(
    <MemoryRouter>
      <AITutorPill />
    </MemoryRouter>,
  );
}

function sseResponse(): Response {
  const body = 'data: {"token":"Namaste"}\n\ndata: {"done":true}\n\n';
  return new Response(body, {
    status: 200,
    headers: { "Content-Type": "text/event-stream" },
  });
}

async function openAndSend(user: ReturnType<typeof userEvent.setup>): Promise<void> {
  await user.click(screen.getByRole("button", { name: "Open AI Tutor" }));
  await user.type(screen.getByLabelText("Message input"), "What is a lot size?");
  await user.click(screen.getByRole("button", { name: "Send message" }));
  // The streamed assistant reply confirms the request round-trip completed.
  expect(await screen.findByText("Namaste")).toBeInTheDocument();
}

function requestBody(fetchMock: ReturnType<typeof vi.fn>): Record<string, unknown> {
  const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
  return JSON.parse(String(init.body)) as Record<string, unknown>;
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("AITutorPill", () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    vi.clearAllMocks();
    authState.token = null;
    authState.status = "logged-out";
    useAIConversationStore.setState({
      messages: [],
      isStreaming: false,
      currentRoute: "/",
      conversationId: null,
    });
    fetchMock = vi.fn().mockResolvedValue(sseResponse());
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("renders the minimised Ask AI pill when the tutor preference is enabled", () => {
    renderPill();

    expect(screen.getByRole("button", { name: "Open AI Tutor" })).toBeInTheDocument();
    expect(screen.getByText("Ask AI")).toBeInTheDocument();
  });

  it("sends session_id on real auth sessions so tutor chats are captured server-side", async () => {
    authState.token = "real-jwt";
    useAIConversationStore.setState({ conversationId: "tutor-conv-1" });
    const user = userEvent.setup();
    renderPill();

    await openAndSend(user);

    const [url] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(String(url)).toMatch(/\/api\/v1\/advisor\/stream$/);
    const body = requestBody(fetchMock);
    expect(body.session_id).toBe("tutor-conv-1");
    expect(body.context).toMatchObject({ route: "/" });
  });

  it("omits session_id on demo auth sessions so fabricated chats never persist", async () => {
    authState.token = "demo-user";
    useAIConversationStore.setState({ conversationId: "tutor-conv-1" });
    const user = userEvent.setup();
    renderPill();

    await openAndSend(user);

    expect(requestBody(fetchMock)).not.toHaveProperty("session_id");
  });

  it("passes session_id to the non-streaming fallback when streaming is unavailable", async () => {
    authState.token = "real-jwt";
    useAIConversationStore.setState({ conversationId: "tutor-conv-1" });
    fetchMock
      .mockResolvedValueOnce(new Response("Not found", { status: 404 }))
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({ status: "success", data: { response: "Fallback reply" } }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        ),
      );
    const user = userEvent.setup();
    renderPill();

    await user.click(screen.getByRole("button", { name: "Open AI Tutor" }));
    await user.type(screen.getByLabelText("Message input"), "What is a lot size?");
    await user.click(screen.getByRole("button", { name: "Send message" }));

    expect(await screen.findByText("Fallback reply")).toBeInTheDocument();
    const [fallbackUrl, fallbackInit] = fetchMock.mock.calls[1] as [string, RequestInit];
    expect(String(fallbackUrl)).toMatch(/\/api\/v1\/advisor$/);
    const body = JSON.parse(String(fallbackInit.body)) as Record<string, unknown>;
    expect(body.session_id).toBe("tutor-conv-1");
  });
});
