/**
 * llmProviders — shared LLM provider configuration.
 * Used by LLMSection (Settings) and LlmStep (setup wizard).
 */

export interface LLMProviderConfig {
  id: string;
  name: string;
  requiresApiKey: boolean;
  requiresHost: boolean;
  defaultHost?: string;
  defaultModel: string;
}

export type LlmAuthMode = "api-key" | "claude-code-oauth";

export const CLAUDE_CODE_OAUTH_PROVIDER = "claude-code-oauth";

export const LLM_PROVIDERS: readonly LLMProviderConfig[] = [
  { id: "ollama",     name: "Ollama (Managed)", requiresApiKey: false, requiresHost: false, defaultModel: "qwen3:8b"                             },
  { id: "hermes",     name: "Hermes (Nous)",  requiresApiKey: false, requiresHost: true,  defaultModel: "hermes-3"                             },
  { id: "openai",     name: "OpenAI",         requiresApiKey: true,  requiresHost: false, defaultModel: "gpt-4o-mini"                          },
  { id: "anthropic",  name: "Anthropic",      requiresApiKey: true,  requiresHost: false, defaultModel: "claude-3-5-haiku-20241022"            },
  // This is a UI auth choice over the Anthropic provider, not a backend provider.
  { id: CLAUDE_CODE_OAUTH_PROVIDER, name: "Claude Code (OAuth)", requiresApiKey: true, requiresHost: false, defaultModel: "claude-3-5-haiku-20241022" },
  { id: "gemini",     name: "Google Gemini",  requiresApiKey: true,  requiresHost: false, defaultModel: "gemini-2.0-flash"                      },
  { id: "deepseek",   name: "DeepSeek",       requiresApiKey: true,  requiresHost: false, defaultModel: "deepseek-chat"                         },
  { id: "groq",       name: "Groq",           requiresApiKey: true,  requiresHost: false, defaultModel: "llama-3.3-70b-versatile"              },
  { id: "grok",       name: "Grok (xAI)",     requiresApiKey: true,  requiresHost: false, defaultModel: "grok-3-mini"                           },
  { id: "mistral",    name: "Mistral",        requiresApiKey: true,  requiresHost: false, defaultModel: "mistral-small-latest"                 },
  { id: "cerebras",   name: "Cerebras",       requiresApiKey: true,  requiresHost: false, defaultModel: "llama-3.3-70b"                        },
  { id: "together",   name: "Together AI",    requiresApiKey: true,  requiresHost: false, defaultModel: "meta-llama/Llama-3.3-70B-Instruct-Turbo" },
  { id: "openrouter", name: "OpenRouter",     requiresApiKey: true,  requiresHost: false, defaultModel: "openai/gpt-4o-mini"                   },
  { id: "custom",     name: "Custom Endpoint",requiresApiKey: true,  requiresHost: true,  defaultModel: ""                                      },
] as const;

export const LOCAL_PROVIDERS = new Set(["ollama", "hermes"]);

export function normaliseLlmHost(provider: string, host: string | null | undefined): string {
  return provider.trim().toLowerCase() === "ollama" ? "" : String(host ?? "");
}

export function providerSelection(selection: string): { provider: string; authMode: LlmAuthMode } {
  const normalised = selection.trim().toLowerCase();
  if (normalised === CLAUDE_CODE_OAUTH_PROVIDER) {
    return { provider: "anthropic", authMode: "claude-code-oauth" };
  }
  return { provider: normalised, authMode: "api-key" };
}

export function selectionForLlmSettings(provider: string, authMode?: LlmAuthMode): string {
  const normalised = provider.trim().toLowerCase();
  return normalised === "anthropic" && authMode === "claude-code-oauth"
    ? CLAUDE_CODE_OAUTH_PROVIDER
    : normalised;
}
