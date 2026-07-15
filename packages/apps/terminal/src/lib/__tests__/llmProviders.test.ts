import { describe, it, expect } from "vitest";
import {
  LLM_PROVIDERS,
  LOCAL_PROVIDERS,
  providerSelection,
  selectionForLlmSettings,
} from "../llmProviders";

describe("llmProviders", () => {
  it("uses managed Ollama as the local runtime without an LM Studio dependency", () => {
    const ids = LLM_PROVIDERS.map((p) => p.id);
    const ollama = LLM_PROVIDERS.find((provider) => provider.id === "ollama");
    expect(ids).toContain("ollama");
    expect(ids).not.toContain("lmstudio");
    expect(ollama?.requiresHost).toBe(false);
    expect(ollama?.requiresApiKey).toBe(false);
    expect(ollama?.defaultHost).toBeUndefined();
    expect(LOCAL_PROVIDERS.has("ollama")).toBe(true);
    expect(LOCAL_PROVIDERS.has("lmstudio")).toBe(false);
  });

  it("exposes Hermes as a local, host-based agent-model provider (matches the backend HERMES provider)", () => {
    const hermes = LLM_PROVIDERS.find((p) => p.id === "hermes");
    expect(hermes).toBeDefined();
    expect(hermes?.requiresHost).toBe(true);
    expect(hermes?.requiresApiKey).toBe(false); // local Ollama/vLLM host
    expect(hermes?.defaultHost).toBeUndefined();
    expect(LOCAL_PROVIDERS.has("hermes")).toBe(true);
  });

  it("does not classify an arbitrary Custom endpoint as local", () => {
    expect(LOCAL_PROVIDERS.has("custom")).toBe(false);
  });

  it("every host-less provider declares an API-key requirement", () => {
    for (const p of LLM_PROVIDERS) {
      if (!p.requiresHost) expect(typeof p.requiresApiKey).toBe("boolean");
    }
  });

  it("defines provider-specific nonblank model defaults except for arbitrary Custom endpoints", () => {
    for (const provider of LLM_PROVIDERS) {
      if (provider.id === "custom") {
        expect(provider.defaultModel).toBe("");
      } else {
        expect(provider.defaultModel?.trim()).not.toBe("");
      }
    }
    expect(LLM_PROVIDERS.find((provider) => provider.id === "ollama")?.defaultModel).toBe("qwen3:8b");
    expect(LLM_PROVIDERS.find((provider) => provider.id === "openai")?.defaultModel).toBe("gpt-4o-mini");
  });

  it("maps Claude Code OAuth to Anthropic without losing its separate auth mode", () => {
    expect(providerSelection("claude-code-oauth")).toEqual({
      provider: "anthropic",
      authMode: "claude-code-oauth",
    });
    expect(selectionForLlmSettings("anthropic", "claude-code-oauth")).toBe("claude-code-oauth");
    expect(providerSelection("anthropic")).toEqual({ provider: "anthropic", authMode: "api-key" });
  });
});
