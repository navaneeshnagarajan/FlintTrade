import { describe, it, expect } from "vitest";
import { LLM_PROVIDERS, LOCAL_PROVIDERS } from "../llmProviders";

describe("llmProviders", () => {
  it("exposes the local providers the mission requires (Ollama + LM Studio)", () => {
    const ids = LLM_PROVIDERS.map((p) => p.id);
    expect(ids).toContain("ollama");
    expect(ids).toContain("lmstudio");
    expect(LOCAL_PROVIDERS.has("ollama")).toBe(true);
    expect(LOCAL_PROVIDERS.has("lmstudio")).toBe(true);
  });

  it("exposes Hermes as a local, host-based agent-model provider (matches the backend HERMES provider)", () => {
    const hermes = LLM_PROVIDERS.find((p) => p.id === "hermes");
    expect(hermes).toBeDefined();
    expect(hermes?.requiresHost).toBe(true);
    expect(hermes?.requiresApiKey).toBe(false); // local Ollama/vLLM host
    expect(LOCAL_PROVIDERS.has("hermes")).toBe(true);
  });

  it("every host-less provider declares an API-key requirement", () => {
    for (const p of LLM_PROVIDERS) {
      if (!p.requiresHost) expect(typeof p.requiresApiKey).toBe("boolean");
    }
  });
});
