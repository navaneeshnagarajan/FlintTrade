import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";
import AIAdvisorWidget from "../AIAdvisorWidget";
import { useAIConversationStore } from "@/stores/aiConversationStore";
import { useModeStore } from "@/stores/modeStore";

const voice = vi.hoisted(() => ({
  supported: true,
  listening: false,
  onResult: undefined as ((text: string) => void) | undefined,
  onError: undefined as ((error: string) => void) | undefined,
  start: vi.fn(), stop: vi.fn(), abort: vi.fn(),
}));
const chat = vi.hoisted(() => ({ ready: true, reply: vi.fn(), place: vi.fn() }));
vi.mock("@/hooks/useVoiceInput", () => ({
  useVoiceInput: (options: { onResult: (text: string) => void; onError: (error: string) => void }) => {
    voice.onResult = options.onResult;
    voice.onError = options.onError;
    return { isSupported: voice.supported, isListening: voice.listening,
      transcript: "", startListening: voice.start, stopListening: voice.stop,
      abort: voice.abort, clearTranscript: vi.fn() };
  },
}));
vi.mock("@/hooks/useAdvisorLlmStatus", () => ({
  useAdvisorLlmStatus: () => ({ configured: chat.ready, chrome: chat.ready ? "ready" : "unconfigured", refetch: vi.fn() }),
}));
vi.mock("@/services/advisorChat", () => ({
  advisorLlmChromeLabel: () => "Connected (suggest only)",
  requestAdvisorReply: chat.reply,
}));
vi.mock("@/services/api", () => ({ placeOrder: chat.place }));

function renderChat() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const ui = () => <QueryClientProvider client={client}><AIAdvisorWidget node={{}} /></QueryClientProvider>;
  return { ...render(ui()), ui };
}
const proposal = '[TOOL_CALL:Buy one RELIANCE|orders/place|POST|{"symbol":"RELIANCE","exchange":"NSE","action":"BUY","quantity":1,"orderType":"MARKET","product":"CNC"}]';

beforeEach(() => {
  vi.clearAllMocks();
  voice.supported = true;
  voice.listening = false;
  chat.ready = true;
  chat.reply.mockResolvedValue(proposal);
  chat.place.mockResolvedValue({ orderId: "PRACTICE-VOICE" });
  useAIConversationStore.getState().clearMessages();
  useModeStore.setState({ mode: "practice" });
});

describe("AI conversation dictation", () => {
  it("keeps recognised speech editable until Send and places only after approval", async () => {
    renderChat();
    fireEvent.click(screen.getByRole("button", { name: "Start voice input" }));
    expect(voice.start).toHaveBeenCalledOnce();
    act(() => voice.onResult?.("Buy one RELIANCE"));
    const draft = screen.getByRole("textbox", { name: "AI conversation draft" });
    expect(draft).toHaveValue("Buy one RELIANCE");
    expect(chat.reply).not.toHaveBeenCalled();
    expect(chat.place).not.toHaveBeenCalled();
    fireEvent.change(draft, { target: { value: "Buy one RELIANCE for delivery" } });
    fireEvent.click(screen.getByRole("button", { name: "Send message" }));
    expect(voice.abort).toHaveBeenCalled();
    await screen.findByRole("button", { name: "Approve" });
    expect(chat.reply.mock.calls[0][0].messages).toEqual([
      { role: "user", content: "Buy one RELIANCE for delivery" },
    ]);
    expect(chat.place).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Approve" }));
    await waitFor(() => expect(chat.place).toHaveBeenCalledWith(
      expect.objectContaining({ symbol: "RELIANCE", quantity: 1, strategy: "AIAdvisor" }),
      { mode: "practice" },
    ));
  });

  it.each(["live", "explore"] as const)("dictation cannot bypass the %s order refusal", async (mode) => {
    useModeStore.setState({ mode });
    renderChat();
    act(() => voice.onResult?.("Buy one RELIANCE"));
    fireEvent.click(screen.getByRole("button", { name: "Send message" }));
    if (mode === "live") {
      await screen.findByText(/cannot place a Live order/);
      expect(screen.queryByRole("button", { name: "Approve" })).toBeNull();
    } else {
      fireEvent.click(await screen.findByRole("button", { name: "Approve" }));
      await screen.findByText(/Action not executed:/);
    }
    expect(chat.place).not.toHaveBeenCalled();
  });

  it("shows listening, stop, and permission-denied states without sending a message", () => {
    const view = renderChat();
    voice.listening = true;
    view.rerender(view.ui());
    expect(screen.getByRole("status")).toHaveTextContent("Listening…");
    fireEvent.click(screen.getByRole("button", { name: "Stop voice input" }));
    expect(voice.stop).toHaveBeenCalledOnce();
    act(() => voice.onError?.("not-allowed"));
    expect(screen.getByRole("alert")).toHaveTextContent("Microphone permission was denied");
    expect(chat.reply).not.toHaveBeenCalled();
    expect(chat.place).not.toHaveBeenCalled();
  });

  it("leaves typing available when the browser cannot recognise speech", () => {
    voice.supported = false;
    renderChat();
    expect(screen.getByRole("button", { name: "Start voice input" })).toBeDisabled();
    expect(screen.getByRole("textbox", { name: "AI conversation draft" })).toBeEnabled();
    expect(screen.getByText(/Voice input is unavailable/)).toBeInTheDocument();
  });

  it("requires a configured advisor and ignores a late transcript when it becomes unavailable", () => {
    const view = renderChat();
    chat.ready = false;
    view.rerender(view.ui());
    act(() => voice.onResult?.("Buy one RELIANCE"));
    expect(screen.getByRole("button", { name: "Start voice input" })).toBeDisabled();
    expect(screen.getByRole("textbox", { name: "AI conversation draft" })).toHaveValue("");
    expect(voice.abort).toHaveBeenCalled();
    expect(chat.reply).not.toHaveBeenCalled();
  });
});
