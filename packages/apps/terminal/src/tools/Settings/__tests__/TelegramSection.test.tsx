/**
 * TelegramSection.test.tsx — persist/hydrate behaviour for the Telegram
 * settings form (real TanStack Query; services mocked).
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";
import "@testing-library/jest-dom";

// Deliberately invalid: these tests use mocked config/send APIs, never Telegram.
const SYNTHETIC_INVALID_BOT_TOKEN = "synthetic-invalid-bot-token";

const runtime = vi.hoisted(() => ({ mode: "live" }));
vi.mock("@/stores/modeStore", () => ({
  useModeStore: (selector: (state: { mode: string }) => unknown) => selector(runtime),
}));
const mockRead = vi.fn();
const mockPersist = vi.fn();
vi.mock("@/services/ftApi.telegram", () => ({
  readTelegramConfig: () => mockRead() as Promise<unknown>,
  persistTelegramConfig: (patch: unknown) => mockPersist(patch) as Promise<unknown>,
}));
vi.mock("@/services/api", () => ({
  sendTelegram: vi.fn(),
}));

import { sendTelegram } from "@/services/api";
import { TelegramSection } from "../TelegramSection";

interface TelegramSettings {
  enabled: boolean;
  botToken: string;
  chatId: string;
}

function Harness({ initial }: { initial: TelegramSettings }) {
  const [settings, setSettings] = useState<TelegramSettings>(initial);
  return (
    <TelegramSection
      settings={settings}
      onChangeField={(field, value) =>
        setSettings((prev) => ({ ...prev, [field]: value }))
      }
    />
  );
}

function renderSection(initial?: Partial<TelegramSettings>) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <Harness initial={{ enabled: false, botToken: "", chatId: "", ...initial }} />
    </QueryClientProvider>,
  );
}

describe("TelegramSection", () => {
  beforeEach(() => {
    runtime.mode = "live";
    vi.mocked(sendTelegram).mockReset().mockResolvedValue({ message: "sent" });
    mockRead.mockReset();
    mockPersist.mockReset();
    mockRead.mockResolvedValue({
      status: "success",
      data: { enabled: false, chat_id: "", bot_token_set: false },
    });
  });

  it("hydrates enabled and chat id from the backend's redacted state", async () => {
    mockRead.mockResolvedValue({
      status: "success",
      data: { enabled: true, chat_id: "-100999", bot_token_set: true },
    });
    renderSection();
    await waitFor(() =>
      expect(screen.getByLabelText("Telegram chat ID")).toHaveValue("-100999"),
    );
    // A stored token is disclosed without being revealed.
    expect(screen.getByLabelText("Telegram bot token")).toHaveAttribute(
      "placeholder",
      expect.stringContaining("saved"),
    );
  });

  it("saves settings through the config endpoint and clears the token field", async () => {
    mockRead.mockResolvedValue({
      status: "success",
      data: { enabled: false, chat_id: "", bot_token_set: false },
    });
    mockPersist.mockResolvedValue({
      status: "ok",
      message: "Telegram settings saved — applying to the running bot",
      data: { enabled: true, chat_id: "77", bot_token_set: true },
    });
    renderSection({ enabled: true, chatId: "77", botToken: SYNTHETIC_INVALID_BOT_TOKEN });

    fireEvent.click(screen.getByRole("button", { name: /save/i }));

    await waitFor(() => expect(mockPersist).toHaveBeenCalledOnce());
    expect(mockPersist).toHaveBeenCalledWith({
      enabled: true,
      chatId: "77",
      botToken: SYNTHETIC_INVALID_BOT_TOKEN,
    });
    // The status line reports what the BACKEND said happened — no hardcoded
    // applied claim when no bot is running or the apply fails.
    expect(
      await screen.findByText(/Telegram settings saved — applying to the running bot/i),
    ).toBeInTheDocument();
    // The token has moved server-side; the field is emptied.
    expect(screen.getByLabelText("Telegram bot token")).toHaveValue("");
  });

  it("reports a rejected save honestly", async () => {
    mockPersist.mockRejectedValue(
      new Error("Enabling Telegram requires both a bot token and a chat id"),
    );
    renderSection({ enabled: true, chatId: "77", botToken: SYNTHETIC_INVALID_BOT_TOKEN });

    fireEvent.click(screen.getByRole("button", { name: /save/i }));

    expect(
      await screen.findByText(/requires both a bot token and a chat id/i),
    ).toBeInTheDocument();
  });

  it("blocks saving an enabled config with no token anywhere", async () => {
    mockRead.mockResolvedValue({
      status: "success",
      data: { enabled: false, chat_id: "", bot_token_set: false },
    });
    renderSection({ enabled: true, chatId: "77", botToken: "" });
    await waitFor(() => expect(mockRead).toHaveBeenCalled());
    expect(screen.getByRole("button", { name: /save/i })).toBeDisabled();
  });

  it("never clobbers a user edit made before the config query resolves", async () => {
    let resolveRead: (value: unknown) => void = () => {};
    mockRead.mockReturnValue(
      new Promise((resolve) => {
        resolveRead = resolve;
      }),
    );
    renderSection({ enabled: true });

    // The user types a chat id while the (slow) config query is in flight.
    fireEvent.change(screen.getByLabelText("Telegram chat ID"), {
      target: { value: "12345" },
    });

    resolveRead({
      status: "success",
      data: { enabled: true, chat_id: "-100999", bot_token_set: true },
    });

    // Untouched field hydrates; the touched one keeps the user's edit.
    await waitFor(() =>
      expect(screen.getByLabelText("Telegram bot token")).toHaveAttribute(
        "placeholder",
        expect.stringContaining("saved"),
      ),
    );
    expect(screen.getByLabelText("Telegram chat ID")).toHaveValue("12345");
  });

  it("allows saving with a blank token when one is already stored", async () => {
    mockRead.mockResolvedValue({
      status: "success",
      data: { enabled: true, chat_id: "77", bot_token_set: true },
    });
    mockPersist.mockResolvedValue({
      status: "ok",
      data: { enabled: true, chat_id: "77", bot_token_set: true },
    });
    renderSection({ enabled: true, chatId: "77" });
    await waitFor(() =>
      expect(screen.getByLabelText("Telegram chat ID")).toHaveValue("77"),
    );
    await waitFor(() =>
      expect(screen.getByLabelText("Telegram bot token")).toHaveAttribute(
        "placeholder",
        expect.stringContaining("saved"),
      ),
    );
    const save = screen.getByRole("button", { name: /save/i });
    expect(save).toBeEnabled();
    fireEvent.click(save);
    await waitFor(() => expect(mockPersist).toHaveBeenCalledOnce());
    expect(mockPersist).toHaveBeenCalledWith({ enabled: true, chatId: "77", botToken: "" });
  });
  it.each(["live", "practice"])("sends a trimmed custom test message on Enter in %s", async (mode) => {
    runtime.mode = mode;
    mockRead.mockResolvedValue({
      status: "success",
      data: { enabled: true, chat_id: "77", bot_token_set: true },
    });
    renderSection();
    const message = await screen.findByRole("textbox", { name: "Telegram test message" });
    await waitFor(() => expect(screen.getByRole("button", { name: "Test Send" })).toBeEnabled());
    fireEvent.change(message, { target: { value: "  Custom safety alert  " } });
    fireEvent.keyDown(message, { key: "Enter" });
    await waitFor(() => expect(sendTelegram).toHaveBeenCalledWith("Custom safety alert", {
      botToken: "",
      chatId: "77",
    }));
  });

  it("rejects a whitespace-only test message on click and Enter", async () => {
    mockRead.mockResolvedValue({
      status: "success", data: { enabled: true, chat_id: "77", bot_token_set: true },
    });
    renderSection();
    const message = await screen.findByRole("textbox", { name: "Telegram test message" });
    fireEvent.change(message, { target: { value: "   " } });
    expect(screen.getByRole("button", { name: "Test Send" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Test Send" }));
    fireEvent.keyDown(message, { key: "Enter" });
    expect(sendTelegram).not.toHaveBeenCalled();
  });

  it("keeps Example disarmed even with stored credentials and a custom message", async () => {
    runtime.mode = "explore";
    mockRead.mockResolvedValue({
      status: "success", data: { enabled: true, chat_id: "77", bot_token_set: true },
    });
    renderSection({ enabled: true, chatId: "77", botToken: "test-token" });
    const message = await screen.findByRole("textbox", { name: "Telegram test message" });
    expect(message).toHaveAttribute("readonly");
    expect(screen.getByRole("button", { name: "Test Send" })).toBeDisabled();
    fireEvent.keyDown(message, { key: "Enter" });
    fireEvent.click(screen.getByRole("button", { name: "Test Send" }));
    expect(sendTelegram).not.toHaveBeenCalled();
    expect(screen.getByText(/Telegram tests are blocked for Example/i)).toBeInTheDocument();
  });
  it("does not dispatch another message while a test send is pending", async () => {
    mockRead.mockResolvedValue({
      status: "success", data: { enabled: true, chat_id: "77", bot_token_set: true },
    });
    vi.mocked(sendTelegram).mockReturnValue(new Promise(() => {}));
    renderSection();
    await waitFor(() => expect(screen.getByRole("button", { name: "Test Send" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "Test Send" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Sending..." })).toBeDisabled());
    fireEvent.keyDown(screen.getByRole("textbox", { name: "Telegram test message" }), { key: "Enter" });
    expect(sendTelegram).toHaveBeenCalledTimes(1);
  });

  it("keeps an unconfigured test disarmed on Enter", async () => {
    renderSection();
    const message = await screen.findByRole("textbox", { name: "Telegram test message" });
    expect(screen.getByRole("button", { name: "Test Send" })).toBeDisabled();
    fireEvent.keyDown(message, { key: "Enter" });
    expect(sendTelegram).not.toHaveBeenCalled();
    expect(screen.getByText("Configure Telegram first")).toBeInTheDocument();
  });
});
