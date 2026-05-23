/**
 * AIAdvisorWidget.test.tsx
 *
 * Tests for the AI Advisor chat widget.
 * Verifies rendering, not-configured state, and chat input.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";

// ---------------------------------------------------------------------------
// Mocks — must be defined before component import
// ---------------------------------------------------------------------------

// Mock settingsStore — default: LLM not configured
const mockLlmProvider = vi.fn(() => "");

vi.mock("@/stores/settingsStore", () => ({
  useSettingsStore: (selector: (s: Record<string, unknown>) => unknown) =>
    selector({
      llm: { provider: mockLlmProvider(), model: "" },
    }),
}));

// Mock aiConversationStore
vi.mock("@/stores/aiConversationStore", () => ({
  useAIConversationStore: (selector: (s: Record<string, unknown>) => unknown) =>
    selector({
      messages: [],
      isStreaming: false,
      addMessage: vi.fn(),
      setStreaming: vi.fn(),
      clearMessages: vi.fn(),
    }),
}));

// Mock advisorApi
vi.mock("@/services/advisorApi", () => ({
  getAdvisorBase: () => "",
}));

// Mock fetch to prevent real network calls (fetchAdvisorStatus on mount)
vi.spyOn(globalThis, "fetch").mockRejectedValue(new Error("No backend"));

// ---------------------------------------------------------------------------
// Import component under test (after mocks)
// ---------------------------------------------------------------------------

import AIAdvisorWidget from "../AIAdvisorWidget";

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("AIAdvisorWidget", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    mockLlmProvider.mockReturnValue("");
    vi.spyOn(globalThis, "fetch").mockRejectedValue(new Error("No backend"));
  });

  it("renders without crashing", () => {
    render(<AIAdvisorWidget />);
    expect(screen.getByText("AI Advisor")).toBeInTheDocument();
  });

  it("shows not-configured state when LLM provider is empty", () => {
    render(<AIAdvisorWidget />);
    expect(screen.getByText("Not configured")).toBeInTheDocument();
    expect(screen.getByText("LLM Not Configured")).toBeInTheDocument();
  });

  it("has a chat input field", () => {
    render(<AIAdvisorWidget />);
    expect(
      screen.getByPlaceholderText("Configure LLM in Settings first..."),
    ).toBeInTheDocument();
  });

  it("has a send button", () => {
    render(<AIAdvisorWidget />);
    expect(screen.getByRole("button", { name: /send message/i })).toBeInTheDocument();
  });
});
