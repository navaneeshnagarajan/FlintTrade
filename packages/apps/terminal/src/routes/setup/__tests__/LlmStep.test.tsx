import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

const persistLlmConfigPatch = vi.hoisted(() => vi.fn());

vi.mock("@/services/ftApi.llm", () => ({
  persistLlmConfigPatch,
}));

import { LlmStep } from "../LlmStep";

describe("LlmStep", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    persistLlmConfigPatch.mockResolvedValue({ status: "ok" });
  });

  it("defaults to managed Ollama without exposing a host, API key, or LM Studio", async () => {
    render(<LlmStep onComplete={vi.fn()} />);

    expect(screen.getByRole("combobox", { name: "LLM provider" })).toHaveTextContent("Ollama (Managed)");
    expect(screen.queryByLabelText("LLM local host URL")).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/API key/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/workspace\.json/i)).not.toBeInTheDocument();
    expect(screen.getByText(/AI Settings.*confirm.*runtime and model downloads/i)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("combobox", { name: "LLM provider" }));
    expect(screen.queryByRole("option", { name: /LM Studio/i })).not.toBeInTheDocument();
  });

  it("collects the provider and model without posting from the pre-auth wizard", async () => {
    const onComplete = vi.fn();
    render(<LlmStep onComplete={onComplete} />);

    fireEvent.click(screen.getByRole("button", { name: "Save and continue" }));

    await waitFor(() => expect(onComplete).toHaveBeenCalledWith({
      provider: "ollama",
      model: "qwen3:8b",
      host: "",
    }));
    expect(persistLlmConfigPatch).not.toHaveBeenCalled();
  });

  it("replaces the model with the selected provider's default", async () => {
    render(<LlmStep onComplete={vi.fn()} />);

    fireEvent.click(screen.getByRole("combobox", { name: "LLM provider" }));
    fireEvent.click(await screen.findByRole("option", { name: "OpenAI" }));

    expect(screen.getByLabelText("LLM model name"))
      .toHaveValue("gpt-4o-mini");
    expect(screen.getByLabelText("LLM model name"))
      .toHaveAttribute("placeholder", "gpt-4o-mini");
  });

  it("preserves Claude Code OAuth as a wizard auth choice", async () => {
    const onComplete = vi.fn();
    render(<LlmStep onComplete={onComplete} />);

    fireEvent.click(screen.getByRole("combobox", { name: "LLM provider" }));
    fireEvent.click(await screen.findByRole("option", { name: "Claude Code (OAuth)" }));
    expect(screen.getByLabelText("LLM model name")).toHaveValue("claude-3-5-haiku-20241022");
    expect(screen.getByLabelText("LLM model name"))
      .toHaveAttribute("placeholder", "claude-3-5-haiku-20241022");

    fireEvent.click(screen.getByRole("button", { name: "Save and continue" }));

    await waitFor(() => expect(onComplete).toHaveBeenCalledWith({
      provider: "claude-code-oauth",
      model: "claude-3-5-haiku-20241022",
      host: "",
    }));
  });

  it("validates a required Custom host before advancing", async () => {
    const onComplete = vi.fn();
    render(<LlmStep onComplete={onComplete} />);

    fireEvent.click(screen.getByRole("combobox", { name: "LLM provider" }));
    fireEvent.click(await screen.findByRole("option", { name: "Custom Endpoint" }));
    fireEvent.click(screen.getByRole("button", { name: "Save and continue" }));

    expect(await screen.findByText("Host URL is required for Custom Endpoint")).toBeInTheDocument();
    expect(onComplete).not.toHaveBeenCalled();
    expect(persistLlmConfigPatch).not.toHaveBeenCalled();
  });

  it("describes Hermes as a local host that does not require credentials", async () => {
    render(<LlmStep onComplete={vi.fn()} />);

    fireEvent.click(screen.getByRole("combobox", { name: "LLM provider" }));
    fireEvent.click(await screen.findByRole("option", { name: "Hermes (Nous)" }));

    expect(screen.getByLabelText("LLM local host URL")).toHaveValue("");
    expect(screen.getByText(/does not require an API key/i)).toBeInTheDocument();
    expect(screen.queryByText(/cloud credentials/i)).not.toBeInTheDocument();
  });

  it("describes Custom as an arbitrary endpoint instead of a local provider", async () => {
    render(<LlmStep onComplete={vi.fn()} />);

    fireEvent.click(screen.getByRole("combobox", { name: "LLM provider" }));
    fireEvent.click(await screen.findByRole("option", { name: "Custom Endpoint" }));

    expect(screen.getByLabelText("LLM host URL")).toHaveValue("");
    expect(screen.queryByLabelText("LLM local host URL")).not.toBeInTheDocument();
    expect(screen.getByText(/endpoint credential.*AI Settings/i)).toBeInTheDocument();
  });

  it("rejects a whitespace-only model before calling the backend", async () => {
    const onComplete = vi.fn();
    render(<LlmStep onComplete={onComplete} />);
    fireEvent.change(screen.getByLabelText("LLM model name"), { target: { value: "   " } });

    fireEvent.click(screen.getByRole("button", { name: "Save and continue" }));

    const error = await screen.findByText("Model is required");
    const model = screen.getByLabelText("LLM model name");
    expect(error).toHaveAttribute("id", "llm-model-error");
    expect(error).toHaveAttribute("role", "alert");
    expect(model).toHaveAttribute("aria-invalid", "true");
    expect(model).toHaveAttribute("aria-describedby", "llm-model-error");
    expect(onComplete).not.toHaveBeenCalled();
    expect(persistLlmConfigPatch).not.toHaveBeenCalled();
  });

  it("associates a missing host error with the Custom host field", async () => {
    render(<LlmStep onComplete={vi.fn()} />);

    fireEvent.click(screen.getByRole("combobox", { name: "LLM provider" }));
    fireEvent.click(await screen.findByRole("option", { name: "Custom Endpoint" }));
    fireEvent.change(screen.getByLabelText("LLM model name"), { target: { value: "custom-model" } });
    fireEvent.click(screen.getByRole("button", { name: "Save and continue" }));

    const error = await screen.findByText("Host URL is required for Custom Endpoint");
    const host = screen.getByLabelText("LLM host URL");
    expect(error).toHaveAttribute("id", "llm-host-error");
    expect(error).toHaveAttribute("role", "alert");
    expect(host).toHaveAttribute("aria-invalid", "true");
    expect(host).toHaveAttribute("aria-describedby", "llm-host-error");
  });
});
