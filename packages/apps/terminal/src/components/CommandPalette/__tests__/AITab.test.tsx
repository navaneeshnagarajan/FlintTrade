import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import "@testing-library/jest-dom";
import { AITab } from "../AITab";

const mockAddMessage = vi.fn();

vi.mock("@/stores/aiConversationStore", () => ({
  useAIConversationStore: vi.fn((selector: (s: Record<string, unknown>) => unknown) =>
    selector({
      messages: [],
      isStreaming: false,
      addMessage: mockAddMessage,
    }),
  ),
}));

describe("AITab", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders the AI input with placeholder", () => {
    render(<AITab query="" onClose={vi.fn()} />);
    expect(screen.getByPlaceholderText(/ask ai anything/i)).toBeInTheDocument();
  });

  it("shows quick prompts when query is empty", () => {
    render(<AITab query="" onClose={vi.fn()} />);
    expect(screen.getByText(/analyse nifty/i)).toBeInTheDocument();
    expect(screen.getByText(/fii.*dii/i)).toBeInTheDocument();
  });

  it("prefills input with stripped @ai query", () => {
    render(<AITab query="analyse NIFTY" onClose={vi.fn()} />);
    const input = screen.getByPlaceholderText(/ask ai anything/i) as HTMLInputElement;
    expect(input.value).toBe("analyse NIFTY");
  });

  it("sends message and navigates to /ai on Enter", () => {
    const onClose = vi.fn();
    const dispatchSpy = vi.spyOn(window, "dispatchEvent");
    render(<AITab query="test query" onClose={onClose} />);

    const input = screen.getByPlaceholderText(/ask ai anything/i);
    fireEvent.keyDown(input, { key: "Enter" });

    expect(mockAddMessage).toHaveBeenCalledWith("user", "test query");
    expect(onClose).toHaveBeenCalled();
    expect(dispatchSpy).toHaveBeenCalled();
    dispatchSpy.mockRestore();
  });

  it("sends message when quick prompt is clicked", () => {
    const onClose = vi.fn();
    render(<AITab query="" onClose={onClose} />);

    fireEvent.click(screen.getByText(/analyse nifty/i));
    expect(mockAddMessage).toHaveBeenCalled();
    expect(onClose).toHaveBeenCalled();
  });
});
